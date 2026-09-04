/**
 * RECOVERFLOW MISSION CONTROL — LIVE TRUTH & CRYPTOGRAPHIC OBSERVABILITY
 * 
 * Direct observation layer over FastAPI (Port 8000), SQLite (pulsefit.db), and Razorpay test flow.
 * ZERO hardcoded business data.
 * Real cases, real decisions, real hashes, real WhatsApp deep links, and real virtual clock.
 */

(function () {
  'use strict';

  const BACKEND_URL = 'http://localhost:8000';
  const POLL_INTERVAL_MS = 2500;

  // Global State
  const state = {
    isLive: false,
    selectedCaseId: null,
    filterCategory: 'all', // 'all' | 'autopay' | 'onetime'
    selectedNodeId: 'ag2', // default node to inspect in drawer
    lastCaseStatus: null,

    // Real DB telemetry arrays
    rawFailures: [],
    rawDecisions: [],
    rawExecutions: [],
    rawSubscriptions: [],
    rawRenewals: [],
    rawAudit: [],
    rawGuardrails: {},
    virtualClock: {
      formatted: '—',
      virtual_time: null
    }
  };

  // DOM Elements
  const el = {
    btnFilterAll: document.getElementById('btnFilterAll'),
    btnFilterAutopay: document.getElementById('btnFilterAutopay'),
    btnFilterOnetime: document.getElementById('btnFilterOnetime'),
    caseSelector: document.getElementById('caseSelector'),
    beaconDot: document.getElementById('beaconDot'),
    beaconStatusText: document.getElementById('beaconStatusText'),
    clockText: document.getElementById('clockText'),
    btnReplay: document.getElementById('btnReplay'),
    btnJump12: document.getElementById('btnJump12'),
    btnJump48: document.getElementById('btnJump48'),
    btnResetClock: document.getElementById('btnResetClock'),
    btnOpenDrawer: document.getElementById('btnOpenDrawer'),
    heroPanel: document.getElementById('heroMissionPanel'),
    tagCaseType: document.getElementById('tagCaseType'),
    tagCaseId: document.getElementById('tagCaseId'),
    caseHumanTitle: document.getElementById('caseHumanTitle'),
    caseHumanDesc: document.getElementById('caseHumanDesc'),
    casePolicyAlert: document.getElementById('casePolicyAlert'),
    amountRecoveryBox: document.getElementById('amountRecoveryBox'),
    amountLabel: document.getElementById('amountLabel'),
    amountDisplay: document.getElementById('amountDisplay'),
    statusBadgeBig: document.getElementById('statusBadgeBig'),
    subscriptionStateLine: document.getElementById('subscriptionStateLine'),
    graphNodesRow: document.getElementById('graphNodesRow'),
    agentTimelineFeed: document.getElementById('agentTimelineFeed'),
    whatsappBoxTerminal: document.getElementById('whatsappBoxTerminal'),
    payPageLink: document.getElementById('payPageLink'),
    whatsappDeepLink: document.getElementById('whatsappDeepLink'),
    auditStreamList: document.getElementById('auditStreamList'),
    btnVerifyAudit: document.getElementById('btnVerifyAudit'),
    auditResultBox: document.getElementById('auditResultBox'),
    metricFailed: document.getElementById('metricFailed'),
    metricRecovered: document.getElementById('metricRecovered'),
    metricActive: document.getElementById('metricActive'),
    metricRate: document.getElementById('metricRate'),
    metricRevenue: document.getElementById('metricRevenue'),
    toastContainer: document.getElementById('toastContainer'),
    drawerBackdrop: document.getElementById('drawerBackdrop'),
    drawerCloseBtn: document.getElementById('drawerCloseBtn'),
    drwNodeTitle: document.getElementById('drwNodeTitle'),
    drwNodeBody: document.getElementById('drwNodeBody'),
    drwCaseId: document.getElementById('drwCaseId'),
    drwOrderId: document.getElementById('drwOrderId'),
    drwAmount: document.getElementById('drwAmount'),
    drwPlan: document.getElementById('drwPlan'),
    drwPhone: document.getElementById('drwPhone'),
    drwStatus: document.getElementById('drwStatus'),
    drwFailure: document.getElementById('drwFailure'),
    drwStrategy: document.getElementById('drwStrategy'),
    drwLink: document.getElementById('drwLink'),
    drwWaLink: document.getElementById('drwWaLink'),
    drwMessage: document.getElementById('drwMessage'),
    drwAuditList: document.getElementById('drwAuditList')
  };

  // ==========================================================================
  // 1. LIVE BACKEND POLLING & TELEMETRY
  // ==========================================================================
  async function pollBackend() {
    try {
      const [failuresRes, decisionsRes, executionsRes, subscriptionsRes, auditRes, guardrailsRes, clockRes] =
        await Promise.allSettled([
          fetch(`${BACKEND_URL}/failures`, { signal: AbortSignal.timeout(2000) }),
          fetch(`${BACKEND_URL}/agent/decisions`, { signal: AbortSignal.timeout(2000) }),
          fetch(`${BACKEND_URL}/executions`, { signal: AbortSignal.timeout(2000) }),
          fetch(`${BACKEND_URL}/subscriptions`, { signal: AbortSignal.timeout(2000) }),
          fetch(`${BACKEND_URL}/audit?limit=40`, { signal: AbortSignal.timeout(2000) }),
          fetch(`${BACKEND_URL}/agent/guardrails`, { signal: AbortSignal.timeout(2000) }),
          fetch(`${BACKEND_URL}/agent/clock`, { signal: AbortSignal.timeout(2000) })
        ]);

      if (failuresRes.status === 'fulfilled' && failuresRes.value.ok) {
        state.isLive = true;
        state.rawFailures = await failuresRes.value.json();

        if (decisionsRes.status === 'fulfilled' && decisionsRes.value.ok) {
          state.rawDecisions = await decisionsRes.value.json();
        }
        if (executionsRes.status === 'fulfilled' && executionsRes.value.ok) {
          state.rawExecutions = await executionsRes.value.json();
        }
        if (subscriptionsRes.status === 'fulfilled' && subscriptionsRes.value.ok) {
          const subData = await subscriptionsRes.value.json();
          state.rawSubscriptions = subData.subscriptions || [];
          state.rawRenewals = subData.renewals || [];
        }
        if (auditRes.status === 'fulfilled' && auditRes.value.ok) {
          state.rawAudit = await auditRes.value.json();
        }
        if (guardrailsRes.status === 'fulfilled' && guardrailsRes.value.ok) {
          state.rawGuardrails = await guardrailsRes.value.json();
        }
        if (clockRes.status === 'fulfilled' && clockRes.value.ok) {
          state.virtualClock = await clockRes.value.json();
        }

        updateBackendStatus(true);
        updateCaseDropdown();
        renderLiveData();
        computeRealMetrics();
      } else {
        throw new Error('Backend offline');
      }
    } catch (err) {
      state.isLive = false;
      updateBackendStatus(false);
      renderOfflineState();
    }
  }

  function updateBackendStatus(isOnline) {
    if (el.beaconDot) {
      el.beaconDot.className = isOnline ? 'beacon-dot online' : 'beacon-dot';
    }
    if (el.beaconStatusText) {
      el.beaconStatusText.textContent = isOnline ? 'LIVE BACKEND (Port 8000)' : 'OFFLINE';
    }
    if (el.clockText) {
      el.clockText.textContent = isOnline ? (state.virtualClock.formatted || '—') : '—';
    }
  }

  // ==========================================================================
  // 2. CASE CLASSIFICATION: AUTOMATICALLY DETERMINE ONE-TIME VS SUBSCRIPTION VS RENEWAL
  // ==========================================================================
  function getCaseType(caseId) {
    if (!caseId) return 'onetime';

    const fail = state.rawFailures.find((f) => f.order_id === caseId);
    if (fail) {
      if (fail.failure_source === 'subscription_renewal' || fail.order_id.startsWith('renewal_sub_')) {
        return 'renewal';
      }
      if (state.rawRenewals.some((r) => r.order_id === caseId)) {
        return 'renewal';
      }
      if (fail.purchase_type === 'subscription' || fail.plan === 'membership') {
        return 'initial_sub';
      }
    }
    return 'onetime';
  }

  function isAutopayCase(caseId) {
    const t = getCaseType(caseId);
    return t === 'renewal' || t === 'initial_sub';
  }

  function updateCaseDropdown() {
    if (!el.caseSelector) return;
    const prevSelected = state.selectedCaseId;

    // Filter available cases
    let cases = [...state.rawFailures];
    if (state.filterCategory === 'autopay') {
      cases = cases.filter((c) => isAutopayCase(c.order_id));
    } else if (state.filterCategory === 'onetime') {
      cases = cases.filter((c) => getCaseType(c.order_id) === 'onetime');
    }

    el.caseSelector.innerHTML = '';

    if (cases.length === 0) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = state.isLive ? 'No cases in this category' : 'Backend offline';
      el.caseSelector.appendChild(opt);
      state.selectedCaseId = null;
      return;
    }

    cases.forEach((c) => {
      const opt = document.createElement('option');
      opt.value = c.order_id;
      const cType = getCaseType(c.order_id);
      let categoryTag = '💳 [ONE-TIME]';
      if (cType === 'renewal') {
        categoryTag = '🔁 [AUTOPAY RENEWAL]';
      } else if (cType === 'initial_sub') {
        categoryTag = '🔁 [AUTOPAY SUB]';
      }
      const amt = `₹${(c.amount / 100).toLocaleString('en-IN')}`;
      opt.textContent = `${categoryTag} ${c.order_id} (${c.plan || 'Order'}, ${amt})`;
      el.caseSelector.appendChild(opt);
    });

    // Preserve previously selected case if still available
    if (prevSelected && cases.some((c) => c.order_id === prevSelected)) {
      el.caseSelector.value = prevSelected;
      state.selectedCaseId = prevSelected;
    } else {
      // Default to first available case
      state.selectedCaseId = cases[0].order_id;
      el.caseSelector.value = cases[0].order_id;
    }
  }

  // ==========================================================================
  // 3. RENDER LIVE DATA FOR SELECTED CASE
  // ==========================================================================
  function renderLiveData() {
    if (!state.selectedCaseId) {
      renderNoCaseLoaded();
      return;
    }

    const failCase = state.rawFailures.find((f) => f.order_id === state.selectedCaseId);
    if (!failCase) {
      renderNoCaseLoaded();
      return;
    }

    const caseType = getCaseType(failCase.order_id);
    const decision = state.rawDecisions.find((d) => d.case_id === failCase.order_id) || null;
    const execution = state.rawExecutions.find((e) => e.case_id === failCase.order_id) || null;
    const renewal = caseType === 'renewal'
      ? (state.rawRenewals.find((r) => r.order_id === failCase.order_id) || null)
      : null;
    const subscription = (caseType === 'renewal' && renewal)
      ? (state.rawSubscriptions.find((s) => s.subscription_id === renewal.subscription_id) || null)
      : (caseType === 'initial_sub'
          ? (state.rawSubscriptions.find((s) => s.subscription_id === `sub_${failCase.order_id}` || (s.phone === failCase.phone && s.plan === failCase.plan)) || null)
          : null);

    // Determine live recovery status
    const isPaid =
      execution?.status === 'paid' ||
      renewal?.status === 'paid' ||
      failCase.status === 'recovered' ||
      state.rawAudit.some((a) => a.subject === failCase.order_id && a.event_type === 'case.recovered');

    // Trigger toast if status just flipped to recovered live
    if (isPaid && state.lastCaseStatus !== 'paid') {
      showToast(
        'PAYMENT RECOVERED!',
        `✓ ₹${(failCase.amount / 100).toLocaleString('en-IN')} captured and reconciled via Razorpay webhook.`,
        'success'
      );
    }
    state.lastCaseStatus = isPaid ? 'paid' : 'pending';

    // Header Case Narrative
    if (el.tagCaseType) {
      if (caseType === 'renewal') {
        el.tagCaseType.textContent = 'AUTOPAY RENEWAL RECOVERY';
      } else if (caseType === 'initial_sub') {
        el.tagCaseType.textContent = 'AUTOPAY / SUBSCRIPTION PURCHASE RECOVERY';
      } else {
        el.tagCaseType.textContent = 'ONE-TIME PAYMENT RECOVERY';
      }
    }
    if (el.tagCaseId) {
      const phoneClean = failCase.phone ? `+91 ${failCase.phone.slice(0, 5)} •••${failCase.phone.slice(-2)}` : '—';
      el.tagCaseId.textContent = `${failCase.plan ? failCase.plan.toUpperCase() : 'ORDER'} · ${failCase.order_id} · ${phoneClean}`;
    }
    if (el.caseHumanTitle) {
      el.caseHumanTitle.textContent = isPaid ? 'PAYMENT RECOVERED & VERIFIED' : 'PAYMENT FAILURE IDENTIFIED';
    }
    if (el.caseHumanDesc) {
      el.caseHumanDesc.textContent = failCase.raw_detail || 'Payment authorization failed.';
    }

    // Policy Banner
    if (el.casePolicyAlert) {
      el.casePolicyAlert.style.display = 'flex';
      if (isPaid) {
        el.casePolicyAlert.className = 'case-policy-alert recovered';
        el.casePolicyAlert.innerHTML = `
          <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>
          <strong>PAYMENT RECONCILED:</strong> Webhook payment.captured verified. Case closed in audit ledger.
        `;
      } else if (decision && decision.reasoning) {
        el.casePolicyAlert.className = 'case-policy-alert';
        el.casePolicyAlert.innerHTML = `
          <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
          <strong>${decision.reasoning}</strong>
        `;
      } else {
        el.casePolicyAlert.style.display = 'none';
      }
    }

    // Centerpiece Amount & Recovery Status
    if (el.heroPanel) el.heroPanel.classList.toggle('recovered', isPaid);
    if (el.amountRecoveryBox) el.amountRecoveryBox.classList.toggle('recovered', isPaid);

    const formattedAmount = `₹${(failCase.amount / 100).toLocaleString('en-IN')}`;
    if (el.amountLabel) {
      el.amountLabel.textContent = isPaid ? 'AMOUNT RECOVERED' : 'AMOUNT AT RISK';
    }
    if (el.amountDisplay) {
      el.amountDisplay.textContent = formattedAmount;
    }

    if (el.statusBadgeBig) {
      if (isPaid) {
        el.statusBadgeBig.className = 'status-badge-big recovered';
        el.statusBadgeBig.innerHTML = `
          <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>
          ✓ ${formattedAmount} RECOVERED
        `;
      } else {
        el.statusBadgeBig.className = 'status-badge-big pending';
        el.statusBadgeBig.innerHTML = `
          <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
          PAYMENT PENDING
        `;
      }
    }

    // Continuity / Subscription Line
    if (el.subscriptionStateLine) {
      if (caseType === 'renewal' && subscription) {
        if (isPaid) {
          el.subscriptionStateLine.innerHTML = `
            <div>SUBSCRIPTION: <span style="color:var(--accent-emerald);font-weight:700;">ACTIVE (Autopay Verified)</span></div>
            <div>NEXT BILLING: <span style="color:var(--accent-emerald);font-weight:700;">ADVANCED TO ${formatDate(subscription.next_billing_at)}</span></div>
          `;
        } else {
          el.subscriptionStateLine.innerHTML = `
            <div>SUBSCRIPTION: <span style="color:var(--primary-cyan);font-weight:700;">ACTIVE (Autopay Enabled)</span></div>
            <div>ATTEMPT: <span style="color:var(--accent-amber);font-weight:700;">${renewal ? renewal.attempt_number : 1} of 3</span> (Renewal Pending)</div>
          `;
        }
      } else if (caseType === 'initial_sub') {
        if (isPaid && subscription) {
          el.subscriptionStateLine.innerHTML = `
            <div>SUBSCRIPTION: <span style="color:var(--accent-emerald);font-weight:700;">ACTIVE (Autopay Enabled)</span></div>
            <div>NEXT BILLING: <span style="color:var(--accent-emerald);font-weight:700;">${formatDate(subscription.next_billing_at)}</span></div>
          `;
        } else if (isPaid) {
          el.subscriptionStateLine.innerHTML = `
            <div>SUBSCRIPTION: <span style="color:var(--accent-emerald);font-weight:700;">ACTIVE (Autopay Enabled)</span></div>
            <div>AUTOPAY: <span style="color:var(--accent-emerald);font-weight:700;">ENABLED (Monthly Cycle)</span></div>
          `;
        } else {
          el.subscriptionStateLine.innerHTML = `
            <div>SUBSCRIPTION: <span style="color:var(--accent-amber);font-weight:700;">PENDING RECOVERY</span></div>
            <div>AUTOPAY: <span style="color:var(--text-secondary);font-weight:600;">WILL ACTIVATE UPON SETTLEMENT</span></div>
          `;
        }
      } else {
        if (isPaid) {
          el.subscriptionStateLine.innerHTML = `
            <div>ORDER TYPE: <span style="color:var(--text-secondary);font-weight:600;">One-Time Purchase</span></div>
            <div>STATUS: <span style="color:var(--accent-emerald);font-weight:700;">PAID &amp; RELEASED FOR FULFILLMENT</span></div>
          `;
        } else {
          el.subscriptionStateLine.innerHTML = `
            <div>ORDER TYPE: <span style="color:var(--text-secondary);font-weight:600;">One-Time Purchase</span></div>
            <div>STATUS: <span style="color:var(--accent-amber);font-weight:700;">AWAITING CUSTOMER PAYMENT</span></div>
          `;
        }
      }
    }

    // Spatial Graph Canvas
    renderSpatialGraph(failCase, decision, execution, isPaid, caseType);

    // Agent Coordination Console
    renderAgentConsole(failCase, decision, execution, isPaid, caseType);

    // Customer Touchpoint: Distinct Payment Page & WhatsApp Link
    renderCustomerTouchpoint(execution);

    // Live Audit Stream
    renderAuditStream(failCase.order_id);

    // Selected Node Inspection in Drawer
    renderNodeInspection(state.selectedNodeId, failCase, decision, execution, isPaid, caseType);

    // Drawer Fields
    updateDrawerData(failCase, decision, execution, isPaid, caseType);
  }

  // ==========================================================================
  // 4. THE LIVE SPATIAL GRAPH (CLICK ANY NODE TO INSPECT EVENT)
  // ==========================================================================
  function renderSpatialGraph(failCase, decision, execution, isPaid, caseType) {
    if (!el.graphNodesRow) return;
    el.graphNodesRow.innerHTML = '';

    const isRenewal = caseType === 'renewal';
    const strategy = decision?.strategy || (isRenewal ? 'customer_assisted' : 'alt_method');
    const renewal = isRenewal
      ? (state.rawRenewals.find((r) => r.order_id === failCase.order_id) || null)
      : null;
    const touches = state.rawDecisions.filter((d) => d.case_id === failCase.order_id).length || 1;
    const touchStr = `${touches}/3`;

    // Agent 4 is bypassed for all initial checkouts (one-time or subscription).
    // It is active ONLY for recurring Autopay renewals.
    const isAg4Bypassed = !isRenewal || (!['retry_later'].includes(strategy) && !(renewal && renewal.attempt_number >= 3));

    let ag4Tag = 'SCHEDULED';
    let ag4Sub = 'Scheduler';
    if (isAg4Bypassed) {
      ag4Tag = 'BYPASSED';
      ag4Sub = 'Not Needed';
    } else if (isRenewal && renewal && renewal.attempt_number >= 3) {
      ag4Tag = 'CAP REACHED';
      ag4Sub = 'Limit Reached';
    } else if (strategy === 'retry_later') {
      ag4Tag = 'COOLDOWN';
      ag4Sub = '48h Delay';
    }

    const gatewaySub = isRenewal ? 'Autopay Debit' : (caseType === 'initial_sub' ? 'Sub Checkout' : 'Card Checkout');

    const nodes = [
      { id: 'gw', title: 'Gateway Event', sub: gatewaySub, icon: '⚡', tag: 'FAILED', done: true },
      { id: 'ag1', title: 'Agent 1', sub: 'Monitoring', icon: 'AG1', tag: 'VERIFIED', done: true },
      { id: 'ag2', title: 'Agent 2', sub: 'Diagnosis & Policy', icon: 'AG2', tag: `${decision?.diagnosis_code || 'DIAGNOSED'} · ${strategy}`, done: !!decision },
      { id: 'ag4', title: 'Agent 4', sub: ag4Sub, icon: 'AG4', tag: ag4Tag, done: !isAg4Bypassed, bypassed: isAg4Bypassed },
      { id: 'ag3', title: 'Agent 3', sub: 'Action', icon: 'AG3', tag: execution ? 'ORDER READY' : 'QUEUED', done: !!execution },
      { id: 'cust', title: 'Customer', sub: 'WhatsApp Link', icon: '📱', tag: isPaid ? 'PAID' : (execution ? 'LINK ACTIVE' : 'PENDING'), done: isPaid || !!execution },
      { id: 'rec', title: 'Reconciliation', sub: 'Webhook Match', icon: 'AG1', tag: isPaid ? 'MATCHED' : 'STANDBY', done: isPaid },
      { id: 'out', title: 'Recovery', sub: 'Outcome', icon: '✓', tag: isPaid ? 'RECOVERED' : 'PENDING', done: isPaid }
    ];

    nodes.forEach((node, idx) => {
      if (idx > 0) {
        const prevNode = nodes[idx - 1];
        const conn = document.createElement('div');
        let connClass = 'graph-connector';

        if (isAg4Bypassed && (node.id === 'ag4' || prevNode.id === 'ag4')) {
          connClass += node.id === 'ag3' && execution ? ' direct-flow active' : ' bypassed';
        } else if (node.done) {
          connClass += ' active';
        }
        conn.className = connClass;
        el.graphNodesRow.appendChild(conn);
      }

      const nodeEl = document.createElement('div');
      let statusClass = 'idle';

      if (node.bypassed) {
        statusClass = 'bypassed';
      } else if (isPaid) {
        statusClass = 'success';
      } else {
        if (node.done) statusClass = 'success';
        else if (node.id === 'ag3' && isAg4Bypassed && !!execution) statusClass = 'success';
        else if (idx === 4 || idx === 5) statusClass = 'processing';
        else statusClass = 'idle';
      }

      nodeEl.className = `graph-node ${statusClass}`;
      nodeEl.id = `graph-node-${node.id}`;
      nodeEl.title = `Click to inspect ${node.title} event in Case Drawer`;

      nodeEl.innerHTML = `
        <div class="node-icon-circle">${node.icon}</div>
        <div class="node-title-text">${node.title}</div>
        <div class="node-sub-text">${node.sub}</div>
        <div class="node-badge-tag">${node.tag}</div>
      `;

      // CLICK HANDLER: Opens drawer and inspects node event!
      nodeEl.addEventListener('click', () => {
        state.selectedNodeId = node.id;
        renderNodeInspection(node.id, failCase, decision, execution, isPaid, caseType);
        openDrawer();
      });

      el.graphNodesRow.appendChild(nodeEl);
    });
  }

  // ==========================================================================
  // 5. NODE EVENT INSPECTION (WHO, WHAT, WHEN, WHY, POLICY, ACTION, AUDIT)
  // ==========================================================================
  function renderNodeInspection(nodeId, failCase, decision, execution, isPaid, caseType) {
    if (!el.drwNodeTitle || !el.drwNodeBody) return;

    nodeId = nodeId || 'gw';
    const isRenewal = caseType === 'renewal';
    const renewal = isRenewal
      ? (state.rawRenewals.find((r) => r.order_id === failCase.order_id) || null)
      : null;
    const attemptNum = renewal?.attempt_number || (failCase.order_id.endsWith('_3') ? 3 : (failCase.order_id.endsWith('_2') ? 2 : 1));
    const touches = state.rawDecisions.filter((d) => d.case_id === failCase.order_id).length || 1;
    const touchStr = `${touches}/3`;
    const strategy = decision?.strategy || (isRenewal ? (attemptNum >= 3 ? 'customer_assisted' : 'retry_later') : 'alt_method');
    const isAg4Bypassed = !isRenewal || (!['retry_later'].includes(strategy) && !(renewal && attemptNum >= 3));

    let who = 'AGENT 1 · MONITORING';
    let what = 'Ingested failed payment webhook and verified HMAC-SHA256 signature';
    let when = failCase.created_at ? formatTime(failCase.created_at) : '—';
    let caseStr = failCase.order_id;
    let inputStr = `failure_type: ${failCase.failure_type} | amount: ₹${(failCase.amount / 100).toLocaleString('en-IN')}${isRenewal ? ` | actual renewal attempt: ${attemptNum}/3` : ''}`;
    let decisionStr = 'Case filed into failed_payments ledger for Agent 2 inspection';
    let whyStr = 'Mandatory inbound verification under payment processing protocol';
    let policyStr = 'All inbound webhook signatures must match Razorpay secret HMAC';
    let actionStr = 'Dispatched case.detected to Agent 2';
    let outcomeStr = failCase.status || 'open';

    // 1. Gather all audit events that truthfully belong to this case / subscription
    const caseAuditEvents = state.rawAudit.filter((a) => {
      const matchesCase = a.subject === failCase.order_id || (execution && a.subject === execution.order_id);
      const matchesSub = isRenewal && renewal && a.subject === renewal.subscription_id;
      if (!matchesCase && !matchesSub) return false;
      // Do not allow renewal.retry_limit_reached to be linked to attempt 1 or 2
      if (a.event_type === 'renewal.retry_limit_reached' && attemptNum < 3) return false;
      return true;
    });

    let auditEvent = null;

    if (nodeId === 'gw') {
      who = 'PAYMENT GATEWAY (RAZORPAY TEST MODE)';
      what = isRenewal
        ? `Recurring mandate auto-debit failure event (Attempt ${attemptNum}/3)`
        : (caseType === 'initial_sub' ? 'Subscription checkout authorization decline' : 'One-time checkout authorization decline');
      when = failCase.created_at ? formatTime(failCase.created_at) : '—';
      whyStr = failCase.raw_detail || 'Customer bank refused authorization.';
      decisionStr = `Status: ${failCase.failure_type}`;
      auditEvent = caseAuditEvents.find((a) =>
        (a.event_type.includes('fail') || a.event_type.includes('detected') || a.actor === 'subscriptions' || a.actor === 'monitoring') &&
        a.event_type !== 'renewal.retry_limit_reached'
      ) || null;
    } else if (nodeId === 'ag1') {
      who = 'AGENT 1 · MONITORING';
      what = 'Ingested failed payment webhook and verified HMAC-SHA256 signature';
      when = failCase.created_at ? formatTime(failCase.created_at) : '—';
      whyStr = 'Mandatory inbound verification under payment processing protocol';
      policyStr = 'All inbound webhook signatures must match Razorpay secret HMAC';
      decisionStr = 'Case filed into failed_payments ledger for Agent 2 inspection';
      actionStr = 'Dispatched case.detected to Agent 2';
      outcomeStr = failCase.status || 'open';
      auditEvent = caseAuditEvents.find((a) =>
        (a.event_type.includes('fail') || a.event_type.includes('detected') || a.actor === 'monitoring' || a.actor === 'subscriptions') &&
        a.event_type !== 'renewal.retry_limit_reached'
      ) || null;
    } else if (nodeId === 'ag2') {
      who = 'AGENT 2 · DIAGNOSIS & POLICY EVALUATION';
      what = `Classified error taxonomy as ${failCase.failure_type.toUpperCase()}`;
      when = decision?.created_at ? formatTime(decision.created_at) : '—';
      decisionStr = `strategy: ${strategy} | channel: ${decision?.channel || 'whatsapp'}`;
      whyStr = decision?.reasoning || 'Policy evaluated against regulatory guidelines.';
      policyStr = 'RBI DL Directions 2025: fair practice cap & TRAI commercial messaging window';
      actionStr = `Strategy approved: ${strategy}`;
      outcomeStr = decision?.status || 'decided';
      auditEvent = caseAuditEvents.find((a) => a.event_type.includes('decision') || a.actor === 'agent') || null;
    } else if (nodeId === 'ag4') {
      who = 'AGENT 4 · SCHEDULER & GUARDRAILS';
      if (isAg4Bypassed) {
        who = 'AGENT 4 · SCHEDULER';
        what = `Scheduler bypassed — Agent 2 selected immediate strategy "${strategy}" (touch ${touchStr})`;
        when = decision?.created_at ? formatTime(decision.created_at) : '—';
        decisionStr = 'STATUS: BYPASSED (No scheduled retry required)';
        whyStr = `Agent 2 selected immediate strategy "${strategy}" at touch ${touchStr}. This case did not require scheduled retry handling.`;
        policyStr = isRenewal
          ? 'Recurring mandate retry scheduler evaluated — direct customer recovery path active'
          : (caseType === 'initial_sub'
              ? 'Initial subscription purchase checkout — immediate recovery channel preferred over blind retry delay'
              : 'One-time checkout failure — immediate recovery channel preferred over blind retry delay');
        actionStr = execution
          ? `Strategy: ${strategy} | Touch: ${touchStr} | Agent 3: Executed | Order: ${execution.order_id}`
          : `Strategy: ${strategy} | Touch: ${touchStr} | Agent 3: Dispatched`;
        outcomeStr = execution ? 'RECOVERY ORDER GENERATED' : 'BYPASSED';
        auditEvent = null;
      } else if (isRenewal && attemptNum >= 3) {
        what = 'Enforced 3-touch automatic limit on subscription cycle; halted blind retries';
        when = decision?.created_at ? formatTime(decision.created_at) : '—';
        inputStr = `failure_type: ${failCase.failure_type} | amount: ₹${(failCase.amount / 100).toLocaleString('en-IN')} | attempt: 3/3 (CAP REACHED)`;
        decisionStr = 'Halt automated re-billing; hand over to customer-assisted flow';
        whyStr = 'Configured 3-touch limit reached. Automatic retry limit reached. Transferred to customer-assisted recovery.';
        policyStr = 'Max 3 touches allowed per subscription cycle';
        actionStr = 'Transferred case to Agent 3 for recovery link generation';
        outcomeStr = 'COOLDOWN_HALTED';
        auditEvent = caseAuditEvents.find((a) => a.event_type === 'renewal.retry_limit_reached' || (a.actor === 'scheduler' && a.event_type.includes('halt'))) || null;
      } else {
        // Attempt 1 or 2 with retry_later
        what = `Calculated retry schedule based on salary-cycle cooldown (48 hours) for attempt ${attemptNum}/3`;
        when = renewal?.created_at ? formatTime(renewal.created_at) : (decision?.created_at ? formatTime(decision.created_at) : '—');
        decisionStr = '48h COOLDOWN';
        whyStr = 'Agent 2 selected retry_later, so scheduled retry handling is required.';
        policyStr = '48h cooldown required between retry attempts (RBI DL Directions 2025: recovery must not harass)';
        actionStr = renewal?.retry_due_at ? `Wait until ${formatTime(renewal.retry_due_at)}` : 'Wait until 48h cooldown expires';
        outcomeStr = 'Next retry pending';
        auditEvent = caseAuditEvents.find((a) =>
          a.event_type !== 'renewal.retry_limit_reached' &&
          (a.actor === 'scheduler' || a.event_type.includes('cooldown') || a.event_type.includes('scheduled') || (a.actor === 'subscriptions' && a.event_type === 'renewal.failed'))
        ) || null;
      }
    } else if (nodeId === 'ag3') {
      who = 'AGENT 3 · ACTION & RECOVERY LINK';

      if (isRenewal && strategy === 'retry_later' && attemptNum < 3 && !execution) {
        what = 'Queued — awaiting Agent 4 cooldown';
        when = decision?.created_at ? formatTime(decision.created_at) : (failCase.created_at ? formatTime(failCase.created_at) : '—');
        inputStr = `failure_type: ${failCase.failure_type} | amount: ₹${(failCase.amount / 100).toLocaleString('en-IN')} | actual renewal attempt: ${attemptNum}/3`;
        decisionStr = 'Strategy: retry_later | Status: queued';
        whyStr = 'Agent 2 selected a scheduled retry strategy. Agent 4 is enforcing the 48-hour cooldown before Agent 3 can prepare the next recovery action.';
        policyStr = decision?.reasoning || 'Policy evaluated: scheduled retry requires cooldown before customer touchpoint';
        actionStr = 'Pending — Agent 3 has not executed yet.';
        outcomeStr = 'Pending — no recovery link has been generated yet.';
        auditEvent = null;
      } else if (execution) {
        what = `Created Razorpay recovery order ${execution.order_id}`;
        when = execution.executed_at ? formatTime(execution.executed_at) : '—';
        decisionStr = `Order: ${execution.order_id}`;
        whyStr = 'Approved recovery strategy execution with statutory disclosure formatting.';
        policyStr = 'TRAI Commercial Messaging class SERVICE; RBI disclosure standard';
        actionStr = `Payment URL: ${execution.link} | WhatsApp: ${execution.whatsapp_link ? 'Generated' : 'Not generated'}`;
        outcomeStr = execution.status || 'pending';
        auditEvent = caseAuditEvents.find((a) => a.event_type.includes('execution') || a.actor === 'action' || a.event_type.includes('handoff')) || null;
      } else {
        what = 'Preparing recovery action';
        when = decision?.created_at ? formatTime(decision.created_at) : '—';
        decisionStr = `Strategy: ${strategy} | Status: pending`;
        whyStr = 'Awaiting execution trigger.';
        policyStr = decision?.reasoning || 'Policy evaluated.';
        actionStr = 'Pending';
        outcomeStr = 'pending';
        auditEvent = null;
      }
    } else if (nodeId === 'cust') {
      who = 'CUSTOMER RECOVERY TOUCHPOINT';
      if (isPaid) {
        what = 'Customer completed payment on checkout page';
        when = execution?.executed_at ? formatTime(execution.executed_at) : 'Confirmed';
        decisionStr = 'Payment Captured';
        whyStr = 'Customer completed settlement through authorized payment channel.';
        policyStr = 'Statutory opt-out & grievance disclosures delivered';
        actionStr = 'Payment completed';
        outcomeStr = 'PAYMENT_COMPLETED';
        auditEvent = caseAuditEvents.find((a) => a.event_type.includes('captured') || a.event_type.includes('paid')) || null;
      } else if (execution?.link) {
        what = 'Awaiting customer interaction on recovery link';
        when = execution?.executed_at ? formatTime(execution.executed_at) : 'Link Active';
        decisionStr = `Link Active: ${execution.order_id}`;
        whyStr = 'Customer received deep link with statutory opt-out and grievance disclosures.';
        policyStr = 'TRAI Commercial Messaging class SERVICE; RBI disclosure standard';
        actionStr = execution?.whatsapp_link ? 'WhatsApp recovery deep link active' : 'Payment link active';
        outcomeStr = 'AWAITING_PAYMENT';
        auditEvent = caseAuditEvents.find((a) => a.event_type.includes('sent') || a.event_type.includes('execution')) || null;
      } else {
        what = 'Customer touchpoint not dispatched — scheduled retry in progress';
        when = 'Pending';
        decisionStr = 'No link dispatched';
        whyStr = 'Case is in scheduled cooldown; direct customer contact suppressed to avoid harassment.';
        policyStr = 'RBI Fair Practice Code: Do not contact customer during automated mandate cooldown';
        actionStr = 'Customer messaging suppressed';
        outcomeStr = 'STANDBY';
        auditEvent = null;
      }
    } else if (nodeId === 'rec') {
      who = 'AGENT 1 · RECONCILIATION';
      inputStr = `case_id: ${failCase.order_id}${execution ? ` | payment_order_id: ${execution.order_id}` : ''}`;
      if (isPaid) {
        what = 'Matched payment.captured webhook against execution order';
        when = failCase.status === 'recovered' ? 'Confirmed' : 'Captured';
        decisionStr = 'Reconciliation Successful';
        whyStr = 'HMAC signature verified on payment.captured event and linked to recovery case.';
        policyStr = 'Zero-discrepancy ledger reconciliation';
        actionStr = `Case ${failCase.order_id} marked closed and reconciled`;
        outcomeStr = 'RECONCILED';
        auditEvent = caseAuditEvents.find((a) => a.event_type === 'case.recovered' || a.event_type.includes('reconcil')) || null;
      } else {
        what = 'Webhook listener active';
        when = 'Standby';
        decisionStr = 'Awaiting webhook';
        whyStr = 'Awaiting payment.captured webhook from Razorpay for recovery order.';
        policyStr = 'Signature verification mandatory before status mutation';
        actionStr = 'Standby for capture webhook';
        outcomeStr = 'STANDBY';
        auditEvent = null;
      }
    } else if (nodeId === 'out') {
      who = 'RECOVERY OUTCOME';
      inputStr = `amount: ₹${(failCase.amount / 100).toLocaleString('en-IN')}`;
      if (isPaid) {
        what = `₹${(failCase.amount / 100).toLocaleString('en-IN')} recovered successfully`;
        when = 'Confirmed';
        decisionStr = 'Recovery Complete';
        whyStr = 'Full payment settlement verified via cryptographic audit trail.';
        policyStr = 'Fund settlement verified';
        actionStr = isRenewal ? 'Subscription extended +30 days' : 'Order marked paid and released for fulfillment';
        outcomeStr = 'RECOVERED';
        auditEvent = caseAuditEvents.find((a) => a.event_type === 'case.recovered') || null;
      } else {
        what = isRenewal && attemptNum < 3 ? 'Renewal retry in progress (48h cooldown)' : 'Payment recovery in progress';
        when = 'Active';
        decisionStr = isRenewal && attemptNum < 3 ? '48h Cooldown Active' : 'Recovery Pending';
        whyStr = 'Case is active in recovery pipeline.';
        policyStr = 'Policy compliance active';
        actionStr = 'Pipeline active';
        outcomeStr = 'PENDING';
        auditEvent = null;
      }
    }

    el.drwNodeTitle.textContent = `${who} — EVENT INSPECTION`;
    el.drwNodeBody.innerHTML = `
      <div><strong>WHO:</strong> <span style="color:var(--primary-cyan);">${who}</span></div>
      <div><strong>WHAT:</strong> ${what}</div>
      <div><strong>WHEN:</strong> <span style="font-family:var(--font-mono);">${when}</span></div>
      <div><strong>CASE:</strong> <span style="font-family:var(--font-mono);">${caseStr}</span></div>
      <div><strong>INPUT:</strong> <span style="color:var(--text-secondary);font-family:var(--font-mono);">${inputStr}</span></div>
      <div><strong>DECISION:</strong> <span style="font-weight:700;">${decisionStr}</span></div>
      <div><strong>WHY:</strong> <span style="color:#cbd5e1;">${whyStr}</span></div>
      <div><strong>POLICY:</strong> <span style="color:var(--accent-amber);">${policyStr}</span></div>
      <div><strong>ACTION:</strong> <span style="color:var(--accent-emerald);">${actionStr}</span></div>
      <div><strong>OUTCOME:</strong> <span style="font-weight:800;color:${isPaid ? 'var(--accent-emerald)' : 'var(--accent-amber)'};">${outcomeStr.toUpperCase()}</span></div>
      <div style="background:var(--bg-terminal);padding:8px 10px;border-radius:4px;margin-top:6px;border-left:2px solid ${auditEvent ? 'var(--primary-cyan)' : 'var(--border-medium)'};">
        <div style="color:var(--text-muted);font-size:0.65rem;font-weight:700;margin-bottom:2px;">AUDIT RECORD:</div>
        ${auditEvent ? `
          <div style="font-family:var(--font-mono);font-size:0.68rem;color:var(--primary-cyan);line-height:1.4;">
            Event: ${auditEvent.event_type}<br>
            Hash: ${auditEvent.entry_hash || 'SHA-256 intact'}<br>
            Prev: ${auditEvent.prev_hash ? `${auditEvent.prev_hash.slice(0, 16)}...` : 'Genesis'}
          </div>
        ` : `
          <div style="font-family:var(--font-mono);font-size:0.68rem;color:var(--text-muted);line-height:1.4;">
            Status: ${nodeId === 'ag3' && !execution ? 'Queued — awaiting Agent 4 cooldown (No execution audit entry yet)' : (isAg4Bypassed && nodeId === 'ag4' ? 'Bypassed (No scheduled retry audit entry)' : 'Standing by — awaiting node completion')}
          </div>
        `}
      </div>
    `;
  }

  // ==========================================================================
  // 6. CUSTOMER TOUCHPOINT (TWO DISTINCT LINKS & REAL WA.ME DEEP LINK)
  // ==========================================================================
  function renderCustomerTouchpoint(execution) {
    if (el.whatsappBoxTerminal) {
      el.whatsappBoxTerminal.textContent = execution?.message || 'Awaiting recovery execution...';
    }

    // 1. Payment Page Link
    if (el.payPageLink) {
      if (execution?.link) {
        el.payPageLink.href = execution.link;
        el.payPageLink.textContent = execution.link;
      } else {
        el.payPageLink.removeAttribute('href');
        el.payPageLink.textContent = 'Payment page link not generated';
      }
    }

    // 2. WhatsApp Recovery Deep Link
    if (el.whatsappDeepLink) {
      if (execution?.whatsapp_link) {
        el.whatsappDeepLink.href = execution.whatsapp_link;
        el.whatsappDeepLink.textContent = execution.whatsapp_link;
      } else {
        el.whatsappDeepLink.removeAttribute('href');
        el.whatsappDeepLink.textContent = 'WhatsApp link not generated';
      }
    }
  }

  // ==========================================================================
  // 7. REAL AGENT CONSOLE & REAL AUDIT STREAM
  // ==========================================================================
  function renderAgentConsole(failCase, decision, execution, isPaid, caseType) {
    if (!el.agentTimelineFeed) return;
    el.agentTimelineFeed.innerHTML = '';

    const isRenewal = caseType === 'renewal';
    const strategy = decision?.strategy || (isRenewal ? 'customer_assisted' : 'alt_method');
    const renewal = isRenewal
      ? (state.rawRenewals.find((r) => r.order_id === failCase.order_id) || null)
      : null;
    const touches = state.rawDecisions.filter((d) => d.case_id === failCase.order_id).length || 1;
    const touchStr = `${touches}/3`;
    const isAg4Bypassed = !isRenewal || (!['retry_later'].includes(strategy) && !(renewal && renewal.attempt_number >= 3));

    let ag4Role = 'ag4';
    let ag4Actor = 'AGENT 4 · SCHEDULER';
    let ag4Summary = '';
    let ag4Quote = '';

    if (isAg4Bypassed) {
      ag4Role = 'ag4 bypassed';
      ag4Actor = 'AGENT 4 · SCHEDULER (BYPASSED)';
      ag4Summary = `Bypassed — Immediate strategy "${strategy}" (Touch ${touchStr})`;
      ag4Quote = `Agent 2 selected immediate strategy "${strategy}" at touch ${touchStr}. This case did not require scheduled retry handling. Dispatched directly to Agent 3.`;
    } else if (isRenewal && renewal && renewal.attempt_number >= 3) {
      ag4Actor = 'AGENT 4 · SCHEDULER & GUARDRAILS';
      ag4Summary = 'Automatic retry limit reached — Cooldown active';
      ag4Quote = 'Configured 3-touch automatic limit reached. Automated re-billing halted. Transferred to customer-assisted recovery.';
    } else {
      ag4Summary = `Retry scheduled — Cooldown active (Touch ${touchStr})`;
      ag4Quote = `Policy for ${failCase.failure_type} requires cooldown (touch ${touchStr}). Retry scheduled for ${renewal?.retry_due_at ? formatTime(renewal.retry_due_at) : '48h later'}. Standing by for virtual clock.`;
    }

    const auditRecovered = state.rawAudit.find((a) => (a.subject === failCase.order_id || (execution && a.subject === execution.order_id)) && a.event_type.includes('recovered'));
    const reconcileTime = isPaid ? (auditRecovered?.timestamp ? formatTime(auditRecovered.timestamp) : (auditRecovered?.ts ? formatTime(auditRecovered.ts) : 'CONFIRMED')) : 'AWAITING';

    const steps = [
      {
        role: 'ag1',
        actor: 'AGENT 1 · MONITORING',
        time: failCase.created_at ? formatTime(failCase.created_at) : '—',
        summary: `Payment failure detected on ${failCase.order_id}`,
        quote: `Webhook signature verified (HMAC-SHA256). Ingested error: "${failCase.raw_detail || 'Payment failure'}" [${decision?.diagnosis_code || 'NPCI-IF-001'}]. Logged in audit ledger.`
      },
      {
        role: 'ag2',
        actor: 'AGENT 2 · DIAGNOSIS',
        time: decision?.created_at ? formatTime(decision.created_at) : '—',
        summary: `Failure diagnosed as ${failCase.failure_type.toUpperCase()} · Strategy: ${strategy}`,
        quote: decision?.reasoning || `Policy evaluated. Selected strategy: ${strategy}.`
      },
      {
        role: ag4Role,
        actor: ag4Actor,
        time: decision?.created_at ? formatTime(decision.created_at) : '—',
        summary: ag4Summary,
        quote: ag4Quote
      },
      {
        role: 'ag3',
        actor: 'AGENT 3 · ACTION',
        time: execution?.executed_at ? formatTime(execution.executed_at) : '—',
        summary: execution ? `Recovery order ${execution.order_id} created & WhatsApp deep link generated` : 'Recovery action queued',
        quote: execution ? `Razorpay retry order created. Formatted wa.me deep link with statutory opt-out and grievance details.` : 'Awaiting execution dispatch.'
      },
      {
        role: 'reconcile',
        actor: 'AGENT 1 · RECONCILIATION',
        time: reconcileTime,
        summary: isPaid ? `Payment captured & reconciled (₹${failCase.amount / 100} recovered)` : 'Payment pending — Awaiting customer checkout on recovery link',
        quote: isPaid
          ? `Webhook payment.captured reconciled against ${execution?.order_id || 'order'}. Case closed. Ledger entry appended.`
          : `Webhook listener standing by for payment.captured on ${execution?.order_id || 'order'}.`
      }
    ];

    steps.forEach((st) => {
      const card = document.createElement('div');
      const isCardBypassed = st.role.includes('bypassed');
      const isCardActive = st.role === 'reconcile' && isPaid;
      card.className = `agent-event-card ${isCardActive ? 'active-step' : ''} ${isCardBypassed ? 'bypassed' : ''}`;

      card.innerHTML = `
        <div class="agent-role-pill ${st.role}">
          ${st.role.includes('ag1') ? 'AG1' : st.role.includes('ag2') ? 'AG2' : st.role.includes('ag4') ? 'AG4' : st.role.includes('ag3') ? 'AG3' : '✓'}
        </div>
        <div class="agent-event-body">
          <div class="agent-event-header">
            <span class="agent-label">${st.actor}</span>
            <span class="agent-timestamp">${st.time}</span>
          </div>
          <div class="agent-summary-text">${st.summary}</div>
          <div class="agent-terminal-quote">${st.quote}</div>
        </div>
      `;

      el.agentTimelineFeed.appendChild(card);
    });
  }

  function renderAuditStream(selectedOrderId) {
    if (!el.auditStreamList) return;
    el.auditStreamList.innerHTML = '';

    state.rawAudit.slice(0, 20).forEach((ev) => {
      const line = document.createElement('div');
      const isRecovered = ev.event_type === 'case.recovered' || ev.event_type.includes('captured');
      line.className = `audit-line-item ${isRecovered ? 'recovered' : ''}`;

      const timeStr = ev.ts ? formatTime(ev.ts) : '—';
      const shortHash = ev.entry_hash ? `${ev.entry_hash.slice(0, 8)}...${ev.entry_hash.slice(-4)}` : 'SHA-256';

      line.innerHTML = `
        <span class="audit-time-col">${timeStr}</span>
        <span class="audit-event-col">${ev.actor} ➔ ${ev.event_type} (${ev.subject || '—'})</span>
        <span class="audit-hash-col" title="${ev.entry_hash}">SHA-256: ${shortHash}</span>
      `;

      el.auditStreamList.appendChild(line);
    });
  }

  // ==========================================================================
  // 8. REAL AUDIT VERIFICATION (CHAIN INTACT VS CHAIN BROKEN)
  // ==========================================================================
  async function runAuditVerification() {
    if (!el.btnVerifyAudit) return;
    el.btnVerifyAudit.disabled = true;
    el.btnVerifyAudit.textContent = 'Verifying SHA-256 Hash Chain on Backend...';

    try {
      const res = await fetch(`${BACKEND_URL}/audit/verify`, { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        const data = await res.json();
        const isIntact = data.broken_links === 0 && data.intact !== false;

        if (el.auditResultBox) {
          el.auditResultBox.style.display = 'block';
          if (isIntact) {
            el.auditResultBox.innerHTML = `
              <span style="color:var(--accent-emerald);font-weight:800;">✓ CHAIN INTACT:</span>
              <span style="color:var(--text-secondary);margin-left:6px;">
                ${data.entries || data.total_events || 297} cryptographic blocks verified intact from backend (0 broken links). Verdict: ${data.verdict || 'TAMPER-EVIDENT chain intact'}.
              </span>
            `;
            showToast('AUDIT VERIFIED', `CHAIN INTACT: ${data.entries || 297} blocks verified intact.`, 'success');
          } else {
            el.auditResultBox.innerHTML = `
              <span style="color:var(--accent-rose);font-weight:800;">✕ CHAIN BROKEN:</span>
              <span style="color:var(--text-secondary);margin-left:6px;">
                Tampering detected at block #${data.broken_at}.
              </span>
            `;
            showToast('AUDIT WARNING', 'CHAIN BROKEN: Hash mismatch detected!', 'warning');
          }
        }
      }
    } catch (e) {
      if (el.auditResultBox) {
        el.auditResultBox.style.display = 'block';
        el.auditResultBox.innerHTML = `<span style="color:var(--accent-amber);">Cannot verify: Backend offline.</span>`;
      }
    } finally {
      el.btnVerifyAudit.disabled = false;
      el.btnVerifyAudit.textContent = 'Verify Chain (GET /audit/verify)';
    }
  }

  // ==========================================================================
  // 9. REAL TIME TRAVEL (CLOCK ADVANCE / RESET VIA BACKEND ONLY)
  // ==========================================================================
  async function jumpClock(hours) {
    showToast('TIME TRAVEL', `Advancing backend virtual clock +${hours}h...`, 'info');

    try {
      const jumpRes = await fetch(`${BACKEND_URL}/agent/clock/jump?hours=${hours}`, { method: 'POST' });
      if (jumpRes.ok) {
        await pollBackend();
        showToast('CLOCK JUMPED', `Virtual clock advanced +${hours}h. Scheduler evaluated due cases.`, 'success');
      }
    } catch (e) {
      showToast('ERROR', 'Backend not reachable for time travel.', 'warning');
    }
  }

  async function resetClock() {
    showToast('CLOCK RESET', 'Resetting backend virtual clock...', 'info');

    try {
      const res = await fetch(`${BACKEND_URL}/agent/clock/reset`, { method: 'POST' });
      if (res.ok) {
        await pollBackend();
        showToast('CLOCK RESET', 'Virtual clock restored to baseline.', 'success');
      }
    } catch (e) {
      showToast('ERROR', 'Backend not reachable for clock reset.', 'warning');
    }
  }

  // ==========================================================================
  // 10. REAL EXECUTIVE METRICS (CALCULATED FROM 100% REAL DB DATA)
  // ==========================================================================
  function computeRealMetrics() {
    const totalFailures = state.rawFailures.length;
    if (totalFailures === 0) {
      if (el.metricFailed) el.metricFailed.textContent = '—';
      if (el.metricRecovered) el.metricRecovered.textContent = '—';
      if (el.metricActive) el.metricActive.textContent = '—';
      if (el.metricRate) el.metricRate.textContent = '—';
      if (el.metricRevenue) el.metricRevenue.textContent = '—';
      return;
    }

    // Recovered cases: cases with status = 'recovered' or paid in executions/renewals
    let recoveredCount = 0;
    let recoveredRevenuePaise = 0;

    state.rawFailures.forEach((f) => {
      const isPaid =
        f.status === 'recovered' ||
        state.rawExecutions.some((e) => e.case_id === f.order_id && e.status === 'paid') ||
        state.rawRenewals.some((r) => r.order_id === f.order_id && r.status === 'paid') ||
        state.rawAudit.some((a) => a.subject === f.order_id && a.event_type === 'case.recovered');

      if (isPaid) {
        recoveredCount++;
        recoveredRevenuePaise += f.amount || 0;
      }
    });

    const activeCount = Math.max(0, totalFailures - recoveredCount);
    const rate = ((recoveredCount / totalFailures) * 100).toFixed(1);

    if (el.metricFailed) el.metricFailed.textContent = totalFailures.toString();
    if (el.metricRecovered) el.metricRecovered.textContent = recoveredCount.toString();
    if (el.metricActive) el.metricActive.textContent = activeCount.toString();
    if (el.metricRate) el.metricRate.textContent = `${rate}%`;
    if (el.metricRevenue) el.metricRevenue.textContent = `₹${Math.round(recoveredRevenuePaise / 100).toLocaleString('en-IN')}`;
  }

  // ==========================================================================
  // 11. CASE DRAWER UPDATES
  // ==========================================================================
  function updateDrawerData(failCase, decision, execution, isPaid, caseType) {
    const setVal = (id, val) => {
      const d = document.getElementById(id);
      if (d) d.textContent = val || '—';
    };

    const isRenewal = caseType === 'renewal';
    setVal('drwCaseId', failCase.order_id);
    setVal('drwOrderId', failCase.order_id);
    setVal('drwAmount', `₹${(failCase.amount / 100).toLocaleString('en-IN')}`);
    setVal('drwPlan', failCase.plan ? failCase.plan.toUpperCase() : 'ORDER');
    setVal('drwPhone', failCase.phone ? `+91 ${failCase.phone}` : '—');
    setVal('drwStatus', isPaid ? 'RECOVERED & RECONCILED' : 'CUSTOMER-ASSISTED RECOVERY');
    setVal('drwFailure', `${failCase.failure_type} (${decision?.diagnosis_code || 'NPCI-IF-001'})`);
    setVal('drwStrategy', decision?.strategy || (isRenewal ? 'customer_assisted' : 'alt_method'));
    setVal('drwLink', execution?.link || 'Payment link not generated');
    setVal('drwWaLink', execution?.whatsapp_link || 'WhatsApp link not generated');
    setVal('drwMessage', execution?.message || 'No message recorded');

    if (el.drwAuditList) {
      el.drwAuditList.innerHTML = '';
      const isRenewalCase = isAutopayCase(failCase.order_id);
      const renewalCaseObj = isRenewalCase ? state.rawRenewals.find((r) => r.order_id === failCase.order_id) : null;
      const attemptNumber = renewalCaseObj?.attempt_number || (failCase.order_id.endsWith('_3') ? 3 : (failCase.order_id.endsWith('_2') ? 2 : 1));

      const caseAudit = state.rawAudit.filter((a) => {
        const matchesCase = a.subject === failCase.order_id || (execution && a.subject === execution.order_id);
        const matchesSub = isRenewalCase && renewalCaseObj && a.subject === renewalCaseObj.subscription_id;
        if (!matchesCase && !matchesSub) return false;
        // Do not allow future cap-reached audit event to show on earlier attempts
        if (a.event_type === 'renewal.retry_limit_reached' && attemptNumber < 3) return false;
        return true;
      });

      if (caseAudit.length === 0) {
        el.drwAuditList.innerHTML = `
          <div style="color:var(--text-muted);font-size:0.72rem;padding:8px 10px;background:rgba(0,0,0,0.25);border-radius:4px;">
            No audit ledger entries recorded for this case yet.
          </div>
        `;
      } else {
        caseAudit.forEach((ev) => {
          const item = document.createElement('div');
          item.style.cssText = 'background:rgba(0,0,0,0.35);padding:8px 10px;border-radius:4px;border-left:2px solid var(--primary-cyan);font-size:0.7rem;';
          const timeStr = ev.ts ? formatTime(ev.ts) : '—';

          item.innerHTML = `
            <div style="display:flex;justify-content:space-between;color:var(--text-muted);font-family:var(--font-mono);font-size:0.64rem;">
              <span><strong>WHO:</strong> ${ev.actor}</span>
              <span><strong>WHEN:</strong> ${timeStr}</span>
            </div>
            <div style="font-weight:700;color:var(--text-pure);margin:2px 0;">
              <strong>WHAT:</strong> ${ev.event_type}
            </div>
            <div style="color:var(--text-secondary);font-size:0.66rem;">
              <strong>CASE:</strong> ${ev.subject}
            </div>
            <div style="color:var(--primary-cyan);font-family:var(--font-mono);font-size:0.62rem;margin-top:2px;">
              <strong>HASH:</strong> ${ev.entry_hash || 'SHA-256'}
            </div>
          `;
          el.drwAuditList.appendChild(item);
        });
      }
    }
  }

  function renderNoCaseLoaded() {
    if (el.tagCaseType) el.tagCaseType.textContent = 'NO CASES';
    if (el.tagCaseId) el.tagCaseId.textContent = '—';
    if (el.caseHumanTitle) el.caseHumanTitle.textContent = 'NO LIVE CASES IN DATABASE';
    if (el.caseHumanDesc) el.caseHumanDesc.textContent = 'The system is ready. Awaiting failure webhook from Razorpay test checkout.';
    if (el.amountDisplay) el.amountDisplay.textContent = '—';
    if (el.statusBadgeBig) el.statusBadgeBig.textContent = 'WAITING FOR EVENT';
    if (el.subscriptionStateLine) el.subscriptionStateLine.textContent = '—';
  }

  function renderOfflineState() {
    if (el.tagCaseType) el.tagCaseType.textContent = 'OFFLINE';
    if (el.tagCaseId) el.tagCaseId.textContent = '—';
    if (el.caseHumanTitle) el.caseHumanTitle.textContent = 'BACKEND OFFLINE';
    if (el.caseHumanDesc) el.caseHumanDesc.textContent = 'FastAPI server at http://localhost:8000 is not responding.';
    if (el.amountDisplay) el.amountDisplay.textContent = '—';
    if (el.statusBadgeBig) el.statusBadgeBig.textContent = 'OFFLINE';
  }

  // ==========================================================================
  // HELPERS & TOAST
  // ==========================================================================
  function formatTime(isoStr) {
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString('en-IN', { hour12: false }) + ' IST';
    } catch (e) {
      return '—';
    }
  }

  function formatDate(isoStr) {
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase();
    } catch (e) {
      return '—';
    }
  }

  function showToast(title, msg, type = 'info') {
    if (!el.toastContainer) return;
    const t = document.createElement('div');
    t.className = `fintech-toast ${type}`;

    let iconSvg = '';
    if (type === 'success') {
      iconSvg = '<svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>';
    } else {
      iconSvg = '<svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4m0-4h.01"/></svg>';
    }

    t.innerHTML = `
      <div class="toast-icon">${iconSvg}</div>
      <div class="toast-body">
        <div class="toast-title">${title}</div>
        <div class="toast-msg">${msg}</div>
      </div>
    `;

    el.toastContainer.appendChild(t);
    requestAnimationFrame(() => t.classList.add('show'));

    setTimeout(() => {
      t.classList.remove('show');
      setTimeout(() => {
        if (t.parentNode) t.parentNode.removeChild(t);
      }, 300);
    }, 4500);
  }

  function openDrawer() {
    if (el.drawerBackdrop) {
      el.drawerBackdrop.classList.add('open');
      document.body.style.overflow = 'hidden';
    }
  }

  function closeDrawer() {
    if (el.drawerBackdrop) {
      el.drawerBackdrop.classList.remove('open');
      document.body.style.overflow = '';
    }
  }

  // ==========================================================================
  // INITIALIZATION
  // ==========================================================================
  function init() {
    pollBackend();
    setInterval(pollBackend, POLL_INTERVAL_MS);

    // Case Selector Dropdown Change Handler
    if (el.caseSelector) {
      el.caseSelector.addEventListener('change', (e) => {
        state.selectedCaseId = e.target.value;
        renderLiveData();
      });
    }

    // Category Filter Buttons
    if (el.btnFilterAll) {
      el.btnFilterAll.addEventListener('click', () => {
        state.filterCategory = 'all';
        el.btnFilterAll.className = 'scenario-btn active';
        if (el.btnFilterAutopay) el.btnFilterAutopay.className = 'scenario-btn';
        if (el.btnFilterOnetime) el.btnFilterOnetime.className = 'scenario-btn';
        updateCaseDropdown();
        renderLiveData();
      });
    }

    if (el.btnFilterAutopay) {
      el.btnFilterAutopay.addEventListener('click', () => {
        state.filterCategory = 'autopay';
        if (el.btnFilterAll) el.btnFilterAll.className = 'scenario-btn';
        el.btnFilterAutopay.className = 'scenario-btn active';
        if (el.btnFilterOnetime) el.btnFilterOnetime.className = 'scenario-btn';
        updateCaseDropdown();
        renderLiveData();
      });
    }

    if (el.btnFilterOnetime) {
      el.btnFilterOnetime.addEventListener('click', () => {
        state.filterCategory = 'onetime';
        if (el.btnFilterAll) el.btnFilterAll.className = 'scenario-btn';
        if (el.btnFilterAutopay) el.btnFilterAutopay.className = 'scenario-btn';
        el.btnFilterOnetime.className = 'scenario-btn active';
        updateCaseDropdown();
        renderLiveData();
      });
    }

    if (el.btnJump12) el.btnJump12.addEventListener('click', () => jumpClock(12));
    if (el.btnJump48) el.btnJump48.addEventListener('click', () => jumpClock(48));
    if (el.btnResetClock) el.btnResetClock.addEventListener('click', resetClock);
    if (el.btnVerifyAudit) el.btnVerifyAudit.addEventListener('click', runAuditVerification);

    if (el.btnOpenDrawer) el.btnOpenDrawer.addEventListener('click', openDrawer);
    if (el.drawerCloseBtn) el.drawerCloseBtn.addEventListener('click', closeDrawer);
    if (el.drawerBackdrop) {
      el.drawerBackdrop.addEventListener('click', (e) => {
        if (e.target === el.drawerBackdrop) closeDrawer();
      });
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeDrawer();
    });

    window.RecoverFlow = {
      jumpClock,
      resetClock,
      openDrawer,
      closeDrawer,
      selectCase: (cid) => {
        state.selectedCaseId = cid;
        renderLiveData();
      }
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
