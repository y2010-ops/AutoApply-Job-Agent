// AutoApply frontend — pure vanilla JS, no build step

const $ = (sel) => document.querySelector(sel);
const state = { sessionId: null, applications: [] };

// ---- Step 1: Resume upload ----

const dropZone = $('#dropZone');
const fileInput = $('#resumeInput');
const profilePreview = $('#profilePreview');
const statusDot = $('#statusDot');

dropZone.addEventListener('click', () => fileInput.click());
['dragover', 'dragenter'].forEach(ev =>
  dropZone.addEventListener(ev, e => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  })
);
['dragleave', 'drop'].forEach(ev =>
  dropZone.addEventListener(ev, e => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
  })
);
dropZone.addEventListener('drop', e => {
  const f = e.dataTransfer.files[0];
  if (f) handleResume(f);
});
fileInput.addEventListener('change', e => {
  if (e.target.files[0]) handleResume(e.target.files[0]);
});

async function handleResume(file) {
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    alert('Please upload a PDF.');
    return;
  }
  dropZone.classList.add('processing');
  dropZone.querySelector('.upload-label').textContent = 'Parsing...';

  const fd = new FormData();
  fd.append('resume', file);

  try {
    const res = await fetch('/api/upload-resume', { method: 'POST', body: fd });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    state.sessionId = data.session_id;
    renderProfilePreview(data.profile_preview);
    unlockStep(2);
    statusDot.classList.add('active');
  } catch (err) {
    alert('Failed to parse resume: ' + err.message);
  } finally {
    dropZone.classList.remove('processing');
    dropZone.querySelector('.upload-label').textContent = 'Resume parsed. Continue below.';
  }
}

function renderProfilePreview(p) {
  profilePreview.hidden = false;
  profilePreview.innerHTML = `
    <div class="pp-name">${escapeHtml(p.name || 'Candidate')}</div>
    <div class="pp-stats">
      ${p.experience_count} experiences · ${p.projects_count} projects · ${p.skills_count} skills detected
    </div>
    <div class="pp-skills">
      ${p.top_skills.map(s => `<span class="pp-skill">${escapeHtml(s)}</span>`).join('')}
    </div>
  `;
}

function unlockStep(n) {
  const step = $(`#step${n}`);
  step.classList.remove('disabled');
  step.classList.add('unlocking');
  if (n === 2) $('#runBtn').disabled = false;
}

// ---- Step 2: Run pipeline ----

$('#runBtn').addEventListener('click', async () => {
  if (!state.sessionId) return;

  unlockStep(3);
  $('#loading').hidden = false;
  $('#resultsList').innerHTML = '';
  $('#resultsSummary').hidden = true;
  $('#runBtn').disabled = true;

  cycleLoadingText([
    'Discovering jobs from RemoteOK + HN...',
    'Embedding profile and postings...',
    'LLM scoring top matches...',
    'Tailoring resume bullets...',
    'Drafting cover letters...',
  ]);

  const fd = new FormData();
  fd.append('session_id', state.sessionId);
  fd.append('roles', $('#roles').value);
  fd.append('keywords', $('#keywords').value);
  fd.append('location', $('#location').value);
  fd.append('max_jobs', $('#maxJobs').value);

  try {
    const res = await fetch('/api/run', { method: 'POST', body: fd });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    state.applications = data.applications;
    renderResults(data);
  } catch (err) {
    $('#resultsList').innerHTML = `<p style="color:var(--accent)">Pipeline failed: ${escapeHtml(err.message)}</p>`;
  } finally {
    $('#loading').hidden = true;
    $('#runBtn').disabled = false;
    stopLoadingText();
  }
});

let loadingTimer = null;
function cycleLoadingText(messages) {
  let i = 0;
  $('#loadingText').textContent = messages[0];
  loadingTimer = setInterval(() => {
    i = (i + 1) % messages.length;
    $('#loadingText').textContent = messages[i];
  }, 2500);
}
function stopLoadingText() {
  if (loadingTimer) clearInterval(loadingTimer);
  loadingTimer = null;
}

// ---- Step 3: Render results ----

function renderResults(data) {
  $('#resultsSummary').hidden = false;
  $('#resultsSummary').innerHTML = `
    Found <span class="num">${data.found}</span> jobs ·
    Scored <span class="num">${data.scored}</span> ·
    Tailored <span class="num">${data.tailored}</span> top matches
  `;

  if (!data.applications.length) {
    $('#resultsList').innerHTML = `<p>No matching jobs found. Try broader keywords.</p>`;
    return;
  }

  $('#resultsList').innerHTML = data.applications.map((app, idx) => jobCardHtml(app, idx)).join('');

  // Wire up tabs
  document.querySelectorAll('.job-card').forEach(card => {
    const tabs = card.querySelectorAll('.tab');
    const panels = card.querySelectorAll('.tab-content');
    tabs.forEach((tab, i) => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('active'));
        panels.forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        panels[i].classList.add('active');
      });
    });
  });

  // Wire copy buttons
  document.querySelectorAll('.btn-copy').forEach(btn => {
    btn.addEventListener('click', () => {
      const text = btn.dataset.copy;
      navigator.clipboard.writeText(text).then(() => {
        const orig = btn.textContent;
        btn.textContent = 'Copied ✓';
        setTimeout(() => btn.textContent = orig, 1500);
      });
    });
  });
}

function scoreClass(s) {
  if (s >= 0.75) return 'high';
  if (s >= 0.55) return 'med';
  return 'low';
}

function jobCardHtml(app, idx) {
  const score = Math.round(app.score * 100);
  const scoreCls = scoreClass(app.score);
  const matched = (app.job.tags || []).slice(0, 6);
  const bulletText = (app.tailored_bullets || []).map(b => `• ${b}`).join('\n');

  return `
    <article class="job-card">
      <div class="job-card-head">
        <div>
          <div class="job-card-title">${escapeHtml(app.job.title)}</div>
          <div class="job-card-company">${escapeHtml(app.job.company)} · ${escapeHtml(app.job.source.toUpperCase())} · ${escapeHtml(app.job.location || 'Remote')}</div>
        </div>
        <div class="score-badge ${scoreCls}">${score}</div>
      </div>

      ${app.reasoning ? `<p class="job-reasoning">${escapeHtml(app.reasoning)}</p>` : ''}

      <div class="section-tabs">
        <button class="tab active">Bullets</button>
        <button class="tab">Cover letter</button>
        <button class="tab">Screening answers</button>
      </div>

      <div class="tab-content active">
        <ul class="bullets">
          ${(app.tailored_bullets || []).map(b => `<li>${escapeHtml(b)}</li>`).join('') || '<li>(none generated)</li>'}
        </ul>
      </div>

      <div class="tab-content">
        <div class="cover-letter">${escapeHtml(app.cover_letter || '(none)')}</div>
      </div>

      <div class="tab-content">
        <dl class="answers">
          ${Object.entries(app.answers || {}).map(([k, v]) =>
            `<dt>${escapeHtml(k.replace(/_/g, ' '))}</dt><dd>${escapeHtml(v)}</dd>`
          ).join('') || '<dd>(none)</dd>'}
        </dl>
      </div>

      <div class="job-actions">
        <a href="${escapeAttr(app.apply_url || '#')}" target="_blank" rel="noopener" class="btn-apply">
          Open posting →
        </a>
        <button class="btn-copy" data-copy="${escapeAttr(app.cover_letter || '')}">Copy cover letter</button>
        <button class="btn-copy" data-copy="${escapeAttr(bulletText)}">Copy bullets</button>
      </div>
    </article>
  `;
}

// ---- Utils ----
function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}
function escapeAttr(s) { return escapeHtml(s); }
