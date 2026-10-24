// Customer Support Resolution Agent Frontend Controller

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
}
let currentRunState = null;
let currentTicketId = null;
let demoScenarios = [];

document.addEventListener("DOMContentLoaded", async () => {
  await initializePortal();
  if (portalConfig.demo) await loadScenarios();
  setupEventListeners();
  await refreshPendingApprovals();
  const saved = localStorage.getItem("supportRun");
  if (saved) {
    const response = await fetch(`/api/workflows/${saved}`, {headers: {}});
    if (response.ok) {
      currentRunState = await response.json();
      currentTicketId = currentRunState.ticket_id;
      updateUIWithState(currentRunState);
      await loadTicketAuditTrail(currentTicketId);
    } else if (response.status === 404 || response.status === 401 || response.status === 403) {
      localStorage.removeItem("supportRun");
    }
  }
});

async function loadScenarios() {
  try {
    const res = await fetch("/api/demo/scenarios");
    demoScenarios = await res.json();
    renderScenarioChips(demoScenarios);
  } catch (err) {
    console.error("Failed to load demo scenarios:", err);
  }
}

function renderScenarioChips(scenarios) {
  const container = document.getElementById("scenario-chips");
  container.innerHTML = "";
  
  scenarios.forEach(sc => {
    const chip = document.createElement("button");
    chip.className = "scenario-chip";
    
    let tagClass = "refund";
    if (sc.id.includes("b2")) tagClass = "timeout";
    else if (sc.id.includes("b")) tagClass = "blocked";
    else if (sc.id.includes("c")) tagClass = "timeout";
    else if (sc.id.includes("order")) tagClass = "tracking";
    else if (sc.id.includes("damaged")) tagClass = "damaged";

    chip.innerHTML = `
      <span class="chip-tag ${tagClass}">${sc.category.replace("_", " ")}</span>
      <span>${escapeHtml(sc.title)}</span>
    `;
    chip.onclick = () => selectScenario(sc);
    container.appendChild(chip);
  });
}

function selectScenario(sc) {
  document.getElementById("customer-id").value = sc.customer_id;
  document.getElementById("order-id").value = sc.order_id || "";
  document.getElementById("complaint-message").value = sc.message;
  
  const descEl = document.getElementById("scenario-hint");
  descEl.style.display = "block";
  descEl.innerHTML = `<strong>Selected:</strong> ${escapeHtml(sc.description)}<br><span style="color:#38bdf8;">Expected: ${escapeHtml(sc.expected_outcome)}</span>`;
}

function setupEventListeners() {
  document.getElementById("complaint-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    await submitComplaint();
  });
}

async function submitComplaint() {
  const customerId = document.getElementById("customer-id").value.trim();
  const orderId = document.getElementById("order-id").value.trim() || null;
  const message = document.getElementById("complaint-message").value.trim();

  if (!message) return;

  const submitBtn = document.getElementById("submit-btn");
  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span>Investigating & Resolving...</span>`;

  resetStepper();

  try {
    // 1. Advance stepper to classifying
    setStepState("step-classify", "active");

    const res = await fetch("/api/complaints", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID()
      },
      body: JSON.stringify({
        customer_id: customerId,
        order_id: orderId,
        message: message
      })
    });

    const data = await res.json();
    if (!res.ok) {
      announce(`Error: ${data.detail || "Submission failed"}`);
      return;
    }

    currentRunState = data;
    localStorage.setItem("supportRun", data.run_id);
    currentTicketId = data.ticket_id;
    updateUIWithState(data);
    await loadTicketAuditTrail(data.ticket_id);
    await refreshPendingApprovals();
    await loadHistory();

  } catch (err) {
    console.error("Submission error:", err);
    announce("Network or server error while running agent workflow.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = `<span>Submit to AI Resolution Agent</span>`;
  }
}

function resetStepper() {
  ["step-classify", "step-investigate", "step-policy", "step-proposal", "step-approval", "step-execution", "step-outcome"].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.className = "step-node";
      const desc = el.querySelector(".step-desc");
      if (desc) desc.textContent = desc.getAttribute("data-default") || "";
    }
  });
  document.getElementById("evidence-panel").innerHTML = `<span style="color:var(--text-dim);">No investigation run yet.</span>`;
  document.getElementById("citations-panel").innerHTML = "";
  document.getElementById("approval-container").innerHTML = "";
  document.getElementById("outcome-panel").style.display = "none";
}

function setStepState(stepId, stateClass, text = null) {
  const el = document.getElementById(stepId);
  if (!el) return;
  el.className = `step-node ${stateClass}`;
  if (text) {
    const desc = el.querySelector(".step-desc");
    if (desc) desc.textContent = text;
  }
}

function updateUIWithState(state) {
  document.getElementById("clarification-form").hidden = state.action_type !== "request_clarification";
  if (["QUEUED","NOT_STARTED"].includes(state.execution_status)) {
    announce("Your case is queued for investigation.");
    return;
  }
  // 1. Classification
  setStepState("step-classify", "completed", `Category: ${state.complaint_category} (Order: ${state.order_id || "None"})`);

  // 2. Investigation
  const facts = state.verified_facts || {};
  const hasOrder = facts.order && facts.order.success;
  setStepState("step-investigate", "completed", hasOrder ? `Verified order ${state.order_id} ($${(facts.order.total_amount_minor/100).toFixed(2)})` : "Checked facts against records");

  // Render Evidence
  renderEvidence(facts, state.missing_information);

  // 3. Policy RAG
  const citations = state.policy_references || [];
  setStepState("step-policy", "completed", `Retrieved ${citations.length} policy citations`);
  renderCitations(citations);

  // 4. Propose
  if (state.is_paused && (state.requires_approval || state.action_type === "request_refund_approval")) {
    setStepState("step-proposal", "completed", "Proposed refund requiring supervisor authorization");
    setStepState("step-approval", "paused", "Interrupted: Paused awaiting support reviewer approval");
    renderApprovalPrompt(state);
  } else if (state.reviewer_decision) {
    setStepState("step-proposal", "completed", "Saved refund proposal");
    setStepState("step-approval", "completed", `Reviewer decision: ${state.reviewer_decision.decision}`);
    renderOutcome(state);
  } else if (state.execution_status === "ESCALATED") {
    setStepState("step-proposal", "completed", "Escalation criteria met");
    setStepState("step-approval", "completed", "Skipped (Direct Escalation)");
    setStepState("step-outcome", "completed", "Escalated to Senior Specialist");
    renderOutcome(state);
  } else if (["FAILED", "PENDING_RECONCILIATION", "UNKNOWN"].includes(state.execution_status)) {
    setStepState("step-execution", "paused", state.execution_status);
    renderOutcome(state);
  } else {
    setStepState("step-proposal", "completed", "Prepared direct grounded answer");
    setStepState("step-approval", "completed", "Approval not required for this action");
    setStepState("step-outcome", "completed", "Resolved with customer communication");
    renderOutcome(state);
  }

  if (state.execution_status === "SUCCEEDED") {
    setStepState("step-execution", "completed", `Executed via Gateway Ref: ${state.external_result_reference}`);
    setStepState("step-outcome", "completed", "Refund Verified & Disbursed");
    renderOutcome(state);
  }
}

function renderEvidence(facts, missingInfo) {
  const container = document.getElementById("evidence-panel");
  let html = `<div style="display:flex; flex-direction:column; gap:8px;">`;

  if (facts.order && facts.order.success) {
    const o = facts.order;
    html += `
      <div style="font-size:12px; background:rgba(0,0,0,0.2); padding:8px; border-radius:6px;">
        <strong style="color:#818cf8;">Order ${escapeHtml(o.order_id)}:</strong> Status <code>${escapeHtml(o.status)}</code> | Total: <strong>$${(o.total_amount_minor/100).toFixed(2)}</strong> | Delivered: ${o.delivery_date || 'In Transit'}
      </div>`;
  }

  if (facts.return) {
    const r = facts.return;
    const color = r.status === "INSPECTION_PASSED" ? "#34d399" : (r.status === "IN_TRANSIT" ? "#fbbf24" : "#fb7185");
    html += `
      <div style="font-size:12px; background:rgba(0,0,0,0.2); padding:8px; border-radius:6px;">
        <strong style="color:${color};">Return Intake:</strong> Status <code>${escapeHtml(r.status)}</code> | Tracking: <code>${escapeHtml(r.tracking_number || "N/A")}</code>
        ${r.inspection_notes ? `<br><em style="color:var(--text-muted);">${escapeHtml(r.inspection_notes)}</em>` : ''}
      </div>`;
  }

  if (facts.payment) {
    const p = facts.payment;
    html += `
      <div style="font-size:12px; background:rgba(0,0,0,0.2); padding:8px; border-radius:6px;">
        <strong style="color:#38bdf8;">Payment Ledger:</strong> Paid $${(p.amount_minor/100).toFixed(2)} | Refunded: $${(p.refunded_amount_minor/100).toFixed(2)} | Remaining Balance: <strong>$${(p.refundable_balance_minor/100).toFixed(2)}</strong>
      </div>`;
  }

  if (missingInfo && missingInfo.length > 0) {
    html += `
      <div style="font-size:12px; background:rgba(244,63,94,0.1); border:1px solid rgba(244,63,94,0.2); padding:8px; border-radius:6px; color:#fb7185;">
        <strong>Missing Information:</strong>
        <ul style="margin-left:18px; margin-top:4px;">${missingInfo.map(m => `<li>${escapeHtml(m)}</li>`).join('')}</ul>
      </div>`;
  }

  html += `</div>`;
  container.innerHTML = html;
}

function renderCitations(citations) {
  const container = document.getElementById("citations-panel");
  if (!citations || citations.length === 0) {
    container.innerHTML = `<span style="font-size:12px; color:var(--text-dim);">No specific policy citations required.</span>`;
    return;
  }
  container.innerHTML = citations.map(c => `<span class="citation-pill">📜 ${escapeHtml(c)}</span>`).join(" ");
}

function renderApprovalPrompt(state) {
  const container = document.getElementById("approval-container");
  const facts = state.verified_facts || {};
  const amountMinor = state.proposal_summary?.amount_minor || (facts.payment && facts.payment.refundable_balance_minor) || 0;
  if (!isReviewer()) { container.textContent = "Your refund proposal is awaiting an authorized reviewer."; return; }

  container.innerHTML = `
    <div class="approval-box">
      <div style="font-size:12px; font-weight:700; color:#fbbf24; text-transform:uppercase;">
        ⚠️ Supervisor Authorization Required
      </div>
      <div class="approval-amount">$${(amountMinor/100).toFixed(2)}</div>
      <p style="font-size:13px; color:var(--text-muted); margin-bottom:8px;">
        <strong>Proposal:</strong> ${escapeHtml(state.final_response)} Policy citation: <code>${(state.policy_references || [])[0] || 'refund_policy_v1:section_3'}</code>.
      </p>
      <label for="review-notes">Review notes</label><textarea id="review-notes" class="form-textarea" maxlength="2000"></textarea>
      <p>Expires: ${escapeHtml(state.proposal_summary?.expires_at || "See review queue")}</p>
      <div class="action-row">
        <button class="btn btn-success" id="approve-current">
          ✓ Approve & Disburse Refund
        </button>
        <button class="btn btn-danger" id="reject-current">
          ✕ Reject Request
        </button>
      </div>
    </div>
  `;
  document.getElementById("approve-current").addEventListener("click", () => decideApproval(state.proposed_action_id, "APPROVED"));
  document.getElementById("reject-current").addEventListener("click", () => decideApproval(state.proposed_action_id, "REJECTED"));
}

async function decideApproval(proposalId, decision) {
  const notes = document.getElementById("review-notes")?.value || "";
  const container = document.getElementById("approval-container");
  container.innerHTML = `<span style="color:#fbbf24;">Transacting with Payment Gateway (Idempotency Key Locked)...</span>`;

  try {
    // Look up approval ID
    const pendingRes = await fetch("/api/approvals/pending", {
      headers: {}
    });
    const pendingList = await pendingRes.json();
    const item = pendingList.find(p => p.proposal_id === proposalId);

    if (!item) {
      announce("No pending approval found for this proposal.");
      return;
    }

    const res = await fetch(`/api/approvals/${item.approval_id}/decision`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        decision: decision,
        reviewer_id: portalUser?.id || (demoReviewer ? "rev_supervisor" : undefined),
        reviewer_name: portalUser?.name || (demoReviewer ? "Sarah Jenkins (Support Lead)" : undefined),
        decision_notes: notes
      })
    });

    const result = await res.json();
    if (!res.ok) {
      announce(`Approval error: ${result.detail || "Action failed"}`);
      return;
    }

    // Refresh state
    setStepState("step-approval", "completed", `Decided: ${decision} by authenticated reviewer`);
    
    if (res.status === 202) { announce("Reviewer decision saved. Execution is queued."); await refreshPendingApprovals(); return; }
    const state = result.workflow_state;
    currentRunState = state;
    updateUIWithState(state);
    renderOutcome(state);

    container.innerHTML = `<div style="font-size:13px; color:#34d399; margin-top:8px;">✓ Decision (${decision}) recorded in audit history.</div>`;
    
    if (currentTicketId) {
      await loadTicketAuditTrail(currentTicketId);
    }
    await refreshPendingApprovals();

  } catch (err) {
    console.error("Decision error:", err);
    announce("Error recording reviewer decision.");
  }
}

function renderOutcome(state) {
  const panel = document.getElementById("outcome-panel");
  panel.style.display = "block";

  const isEscalated = state.execution_status === "ESCALATED";
  const box = document.getElementById("outcome-box");
  box.className = `outcome-box ${isEscalated ? 'escalated' : ''}`;

  document.getElementById("outcome-text").textContent = state.final_response || "Inquiry handled.";
  
  const refRow = document.getElementById("outcome-ref-row");
  if (state.external_result_reference) {
    refRow.style.display = "block";
    document.getElementById("outcome-ref").textContent = state.external_result_reference;
  } else {
    refRow.style.display = "none";
  }
}

async function loadTicketAuditTrail(ticketId) {
  try {
    const res = await fetch(`/api/tickets/${ticketId}/audit-trail`, {
      headers: {}
    });
    if (!res.ok) return;
    const trail = await res.json();
    
    const container = document.getElementById("audit-trail");
    if (!trail || trail.length === 0) {
      container.innerHTML = `<span style="font-size:12px; color:var(--text-dim);">No audit events recorded yet.</span>`;
      return;
    }

    container.innerHTML = trail.map(ev => `
      <div class="audit-item">
        <div>
          <span class="audit-action">${escapeHtml(ev.action)}</span>
          <span style="font-size:11px; color:var(--text-dim); margin-left:6px;">(${escapeHtml(ev.entity_type)} ${escapeHtml(ev.entity_id)})</span>
        </div>
        <div class="audit-actor">${escapeHtml(ev.actor_type)}: ${escapeHtml(ev.actor_id)}</div>
      </div>
    `).join("");
  } catch (err) {
    console.error("Failed to load audit trail:", err);
  }
}

async function refreshPendingApprovals() {
  if (!isReviewer()) return;
  try {
    const res = await fetch("/api/approvals/pending", {
      headers: {}
    });
    if (!res.ok) return;
    const items = await res.json();
    
    const countBadge = document.getElementById("pending-count");
    if (countBadge) countBadge.textContent = items.length;
    let queue = document.getElementById("review-queue-list");
    if (!queue) {
      queue = document.createElement("div");
      queue.id = "review-queue-list";
      document.getElementById("reviewer-card").appendChild(queue);
    }
    queue.replaceChildren();
    for (const item of items) {
      const card = document.createElement("div");
      card.className = "queue-item";
      const summary = document.createElement("p");
      summary.textContent = `${item.customer_id} · ${item.order_id} · ${item.currency} ${(item.amount_minor/100).toFixed(2)} · Expires ${item.expires_at}`;
      card.appendChild(summary);
      const reason = document.createElement("p");
      reason.textContent = item.reason;
      card.appendChild(reason);
      const button = document.createElement("button");
      button.className = "btn";
      button.textContent = "Review evidence";
      button.disabled = !item.run_id;
      button.addEventListener("click", async () => {
        const response = await fetch(`/api/workflows/${item.run_id}`, {headers: {}});
        if (!response.ok) return;
        currentRunState = await response.json();
        currentTicketId = currentRunState.ticket_id;
        updateUIWithState(currentRunState);
        await loadTicketAuditTrail(currentTicketId);
      });
      card.appendChild(button);
      queue.appendChild(card);
    }
  } catch (err) {
    console.error("Failed to refresh approvals:", err);
  }
}
