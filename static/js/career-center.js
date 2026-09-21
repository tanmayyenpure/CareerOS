/* =========================================================
   CareerOS · Career Center — interactions
========================================================= */
document.addEventListener('DOMContentLoaded', () => {

  /* ---------- Scroll reveal ---------- */
  const revealEls = document.querySelectorAll('.reveal');
  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('in-view');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });
  revealEls.forEach(el => revealObserver.observe(el));

  /* ---------- Animated counters ---------- */
  const counters = document.querySelectorAll('[data-count]');
  const counterObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const el = entry.target;
      const target = parseInt(el.dataset.count, 10);
      const suffix = el.dataset.suffix || '';
      const duration = 1400;
      const start = performance.now();
      function tick(now){
        const progress = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(eased * target) + suffix;
        if (progress < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
      counterObserver.unobserve(el);
    });
  }, { threshold: 0.4 });
  counters.forEach(el => counterObserver.observe(el));

  /* ---------- Radial progress rings ---------- */
  const radials = document.querySelectorAll('.radial-fill');
  const CIRCUMFERENCE = 2 * Math.PI * 34; // r=34
  const radialObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const el = entry.target;
      const pct = parseFloat(el.dataset.pct || '0');
      const offset = CIRCUMFERENCE - (pct / 100) * CIRCUMFERENCE;
      el.style.strokeDasharray = CIRCUMFERENCE;
      requestAnimationFrame(() => { el.style.strokeDashoffset = offset; });
      radialObserver.unobserve(el);
    });
  }, { threshold: 0.3 });
  radials.forEach(el => radialObserver.observe(el));

  /* ---------- Remote toggle ---------- */
  let isRemotePressed = false;
  const remoteToggle = document.getElementById('remoteToggle');
  if (remoteToggle) {
    remoteToggle.addEventListener('click', () => {
      const pressed = remoteToggle.getAttribute('aria-pressed') === 'true';
      isRemotePressed = !pressed;
      remoteToggle.setAttribute('aria-pressed', String(isRemotePressed));
      triggerSearch();
    });
  }

  /* ---------- Helper to construct search params and query API ---------- */
  async function triggerSearch() {
    const role = document.getElementById('search-role') ? document.getElementById('search-role').value.trim() : '';
    const location = document.getElementById('search-location') ? document.getElementById('search-location').value.trim() : '';
    const experience = document.getElementById('search-experience') ? document.getElementById('search-experience').value : 'Any';
    const salary = document.getElementById('search-salary') ? document.getElementById('search-salary').value : 'Any';
    const company = document.getElementById('search-company') ? document.getElementById('search-company').value.trim() : '';
    const domain = document.getElementById('search-domain') ? document.getElementById('search-domain').value : 'Any';
    
    const params = new URLSearchParams();
    if (role) params.append('role', role);
    if (location) params.append('location', location);
    if (experience && experience !== 'Any') params.append('experience', experience);
    if (salary && salary !== 'Any') params.append('salary', salary);
    if (company) params.append('company', company);
    if (domain && domain !== 'Any') params.append('domain', domain);
    if (isRemotePressed) params.append('remote', 'true');
    
    const jobGrid = document.getElementById('job-grid');
    if (jobGrid) {
      jobGrid.style.opacity = '0.5';
    }
    
    try {
      const response = await fetch(`/career/jobs?${params.toString()}`);
      const jobs = await response.json();
      renderJobs(jobs);
    } catch (err) {
      console.error('Error fetching jobs:', err);
    } finally {
      if (jobGrid) {
        jobGrid.style.opacity = '1';
        jobGrid.animate(
          [{ opacity: .4, transform: 'translateY(6px)' }, { opacity: 1, transform: 'translateY(0)' }],
          { duration: 300, easing: 'ease-out' }
        );
      }
    }
  }

  /* ---------- Search form submit ---------- */
  const searchForm = document.getElementById('searchForm');
  if (searchForm) {
    searchForm.addEventListener('submit', (e) => {
      e.preventDefault();
      triggerSearch();
    });
  }

  /* ---------- Render Jobs Dynamic Cards ---------- */
  function renderJobs(jobs) {
    const jobGrid = document.getElementById('job-grid');
    if (!jobGrid) return;
    
    if (jobs.length === 0) {
      jobGrid.innerHTML = `
        <div class="glass reveal in-view" style="grid-column: 1 / -1; padding: 40px; text-align: center; color: var(--text-muted);">
          <p style="font-size: 1.2rem; margin-bottom: 8px; color: var(--text);">No jobs found</p>
          <p>Try refining your search terms or filters.</p>
        </div>
      `;
      return;
    }
    
    jobGrid.innerHTML = jobs.map(job => {
      const skillsHtml = job.skills_required.map(s => `<span class="tag">${s}</span>`).join('');
      const logoClass = (job.company_logo.toLowerCase() === 'm' || job.company_logo.toLowerCase() === 's' || job.company_logo.toLowerCase() === 'z') ? ' teal' : '';
      
      const actionButtonHtml = job.applied
        ? `<button class="btn btn-ghost btn-sm" disabled style="cursor: not-allowed; opacity: 0.6;">Applied</button>`
        : `<button class="btn btn-primary btn-sm btn-apply" data-job-id="${job.id}">Apply Now</button>`;
        
      const saveButtonHtml = `<button class="btn btn-ghost btn-sm btn-save" data-job-id="${job.id}">${job.saved ? '⭐ Saved' : 'Save'}</button>`;
      
      return `
        <article class="job-card glass reveal in-view" data-job-id="${job.id}">
          <div class="job-card-top">
            <div class="company-logo${logoClass}">${job.company_logo}</div>
            <div>
              <h3 class="job-role">${job.job_title}</h3>
              <p class="job-company">${job.company_name} · ${job.location}</p>
            </div>
            <span class="match-badge">${job.match_pct}% Match</span>
          </div>
          <div class="job-meta">
            <span>💰 ${job.salary}</span>
            <span>🧭 ${job.experience}</span>
            <span>🕐 Posted ${job.posted_date}</span>
            <span>🗂 ${job.job_type}</span>
          </div>
          <div class="skill-tags">
            ${skillsHtml}
          </div>
          <p class="job-desc" style="font-size:0.875rem; color: var(--text-muted); margin: 12px 0 16px 0; line-height: 1.5;">${job.description}</p>
          <div class="job-actions">
            ${actionButtonHtml}
            ${saveButtonHtml}
            <button class="btn btn-text btn-sm btn-details" data-job-id="${job.id}">View Details</button>
          </div>
        </article>
      `;
    }).join('');
    
    bindJobCardEvents(jobGrid);
  }

  /* ---------- Render Recommended Jobs Dynamic Cards ---------- */
  function renderRecommendedJobs(jobs) {
    const recGrid = document.getElementById('recommended-jobs-grid');
    if (!recGrid) return;
    
    const recommended = [...jobs].sort((a, b) => b.match_pct - a.match_pct).slice(0, 4);
    
    if (recommended.length === 0) {
      recGrid.innerHTML = `
        <div class="glass reveal in-view" style="grid-column: 1 / -1; padding: 20px; text-align: center; color: var(--text-muted);">
          No recommended jobs found. Add skills in Settings to see matches.
        </div>
      `;
      return;
    }
    
    recGrid.innerHTML = recommended.map(job => {
      const matchPct = job.match_pct;
      const matchingHtml = job.matching_skills.length > 0 
        ? `Matching: ${job.matching_skills.join(', ')}`
        : 'No matching skills listed yet';
      const missingHtml = job.missing_skills.length > 0 
        ? `Missing: ${job.missing_skills.join(', ')}`
        : 'None! Perfect skill fit';
        
      const gapWeeks = Math.max(1, Math.ceil(job.missing_skills.length * 0.8));
      const CIRCUMFERENCE = 2 * Math.PI * 34; // r=34
      const offset = CIRCUMFERENCE - (matchPct / 100) * CIRCUMFERENCE;
      
      return `
        <article class="rec-card glass reveal in-view">
          <div class="rec-top">
            <div class="rec-score-wrap">
              <svg class="radial" viewBox="0 0 80 80">
                <circle class="radial-track" cx="40" cy="40" r="34"></circle>
                <circle class="radial-fill" cx="40" cy="40" r="34" style="stroke-dasharray: ${CIRCUMFERENCE}; stroke-dashoffset: ${offset}; stroke: var(--gradient-end);" data-pct="${matchPct}"></circle>
              </svg>
              <span class="radial-label">${matchPct}%</span>
            </div>
            <div>
              <h3 class="job-role">${job.job_title}</h3>
              <p class="job-company">${job.company_name} · ${job.job_type}</p>
            </div>
          </div>
          <p class="rec-reason">Strong match with your profile and target role skills.</p>
          <div class="rec-skills">
            <div><span class="dot dot-good"></span>${matchingHtml}</div>
            <div><span class="dot dot-bad"></span>${missingHtml}</div>
            ${job.missing_skills.length > 0 ? `<div class="learn-time">⏱ ~${gapWeeks} week${gapWeeks > 1 ? 's' : ''} to close the gap</div>` : `<div class="learn-time">⏱ Fully prepared!</div>`}
          </div>
          <button class="btn btn-ghost btn-sm full btn-improve-match" data-job-id="${job.id}">Improve Match</button>
        </article>
      `;
    }).join('');
    
    recGrid.querySelectorAll('.btn-improve-match').forEach(btn => {
      btn.addEventListener('click', () => {
        const jobId = btn.dataset.jobId;
        const job = jobs.find(j => j.id == jobId);
        if (job && job.missing_skills.length > 0) {
          alert(`To improve your match for this role, we recommend adding these skills to your profile:\n\n${job.missing_skills.join(', ')}\n\nYou can also generate custom roadmaps for these skills!`);
        } else {
          alert("You already match 100% of the skills required for this job!");
        }
      });
    });
  }

  /* ---------- Render Saved Jobs Dynamic Cards ---------- */
  async function loadSavedJobs() {
    const savedTrack = document.getElementById('saved-jobs-track');
    if (!savedTrack) return;
    
    try {
      const response = await fetch('/career/jobs');
      const jobs = await response.json();
      const saved = jobs.filter(j => j.saved);
      
      if (saved.length === 0) {
        savedTrack.innerHTML = `
          <div style="padding: 20px; text-align: center; color: var(--text-muted); width: 100%;">
            No saved jobs yet. Click 'Save' on any job card above to bookmark it.
          </div>
        `;
        return;
      }
      
      savedTrack.innerHTML = saved.map(job => {
        const logoClass = (job.company_logo.toLowerCase() === 'm' || job.company_logo.toLowerCase() === 's' || job.company_logo.toLowerCase() === 'z') ? ' teal' : '';
        const actionButtonHtml = job.applied
          ? `<button class="btn btn-ghost btn-sm full" disabled style="cursor: not-allowed; opacity: 0.6;">Applied</button>`
          : `<button class="btn btn-primary btn-sm full btn-apply-saved" data-job-id="${job.id}">Quick Apply</button>`;
          
        return `
          <article class="saved-card glass" data-job-id="${job.id}" style="min-width: 220px; flex-shrink: 0; position: relative;">
            <button class="bookmark active btn-unsave-saved" data-job-id="${job.id}" aria-label="Remove bookmark">🔖</button>
            <div class="company-logo${logoClass}">${job.company_logo}</div>
            <h4 style="margin: 8px 0 4px 0; font-size: 0.95rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${job.job_title}</h4>
            <p class="job-company" style="font-size: 0.8rem; margin-bottom: 8px;">${job.company_name} · ${job.location}</p>
            <span class="match-badge sm" style="display: inline-block; margin-bottom: 12px;">${job.match_pct}% Match</span>
            ${actionButtonHtml}
          </article>
        `;
      }).join('');
      
      savedTrack.querySelectorAll('.btn-unsave-saved').forEach(btn => {
        btn.addEventListener('click', async () => {
          const jobId = btn.dataset.jobId;
          try {
            const res = await fetch('/career/save-job', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ job_id: jobId })
            });
            const data = await res.json();
            if (data.success) {
              const savedCounter = document.getElementById('hero-saved-jobs-count');
              if (savedCounter) {
                savedCounter.dataset.count = data.saved_jobs_count;
                savedCounter.textContent = data.saved_jobs_count;
              }
              loadSavedJobs();
              triggerSearch();
              showToast('Job removed from bookmarks.');
            }
          } catch (err) {
            console.error(err);
          }
        });
      });
      
      savedTrack.querySelectorAll('.btn-apply-saved').forEach(btn => {
        btn.addEventListener('click', async () => {
          const jobId = btn.dataset.jobId;
          try {
            const res = await fetch('/career/apply', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ job_id: jobId })
            });
            const data = await res.json();
            if (data.success) {
              const appCounter = document.getElementById('hero-applications-count');
              if (appCounter) {
                appCounter.dataset.count = data.applications_count;
                appCounter.textContent = data.applications_count;
              }
              loadSavedJobs();
              loadApplications();
              triggerSearch();
              showToast('Application submitted successfully!');
            } else if (data.error) {
              showToast(data.error, true);
            }
          } catch (err) {
            console.error(err);
          }
        });
      });
      
    } catch (err) {
      console.error('Error loading saved jobs:', err);
    }
  }

  /* ---------- Render Application Tracker List ---------- */
  async function loadApplications() {
    const appList = document.getElementById('recent-applications-list');
    if (!appList) return;
    
    try {
      const response = await fetch('/career/applications');
      const apps = await response.json();
      
      if (apps.length === 0) {
        appList.innerHTML = `
          <div style="padding: 20px; text-align: center; color: var(--text-muted);">
            No applications submitted yet. Find jobs and click 'Apply Now'.
          </div>
        `;
        return;
      }
      
      appList.innerHTML = apps.map(app => {
        const logoClass = (app.company_logo.toLowerCase() === 'm' || app.company_logo.toLowerCase() === 's' || app.company_logo.toLowerCase() === 'z') ? ' teal' : '';
        
        let statusClass = 'status-yellow';
        if (app.status === 'Interview') statusClass = 'status-blue';
        if (app.status === 'Rejected') statusClass = 'status-red';
        if (app.status === 'Offer' || app.status === 'Joined') statusClass = 'status-green';
        
        return `
          <div class="app-row" data-app-id="${app.id}">
            <div class="company-logo sm${logoClass}">${app.company_logo}</div>
            <span class="app-name">${app.company_name} — ${app.job_title}</span>
            <span class="status ${statusClass}">${app.status}</span>
          </div>
        `;
      }).join('');
      
    } catch (err) {
      console.error('Error loading applications:', err);
    }
  }

  /* ---------- Render Upcoming Interviews ---------- */
  async function loadInterviews() {
    const intGrid = document.getElementById('interviews-grid');
    if (!intGrid) return;
    
    try {
      const response = await fetch('/career/interviews');
      const interviews = await response.json();
      
      if (interviews.length === 0) {
        intGrid.innerHTML = `
          <div class="glass reveal in-view" style="grid-column: 1 / -1; padding: 30px; text-align: center; color: var(--text-muted); width: 100%;">
            No upcoming interviews scheduled yet.
          </div>
        `;
        return;
      }
      
      intGrid.innerHTML = interviews.map(i => {
        const logoClass = (i.company_name.substring(0,1).toLowerCase() === 'm' || i.company_name.substring(0,1).toLowerCase() === 's') ? ' teal' : '';
        
        return `
          <article class="interview-card glass in-view">
            <div class="job-card-top">
              <div class="company-logo${logoClass}">${i.company_name.substring(0,1)}</div>
              <div>
                <h3 class="job-role">${i.job_title}</h3>
                <p class="job-company">${i.company_name} · ${i.round_name}</p>
              </div>
            </div>
            <div class="interview-meta">
              <span>📅 ${i.interview_date_str}</span>
              <span>🕓 ${i.interview_time_str}</span>
              <span class="mode online">● Online</span>
            </div>
            <div class="countdown" data-target="${i.interview_date}">
              <span class="cd-seg"><b class="cd-d">--</b>d</span>
              <span class="cd-seg"><b class="cd-h">--</b>h</span>
              <span class="cd-seg"><b class="cd-m">--</b>m</span>
            </div>
            <div class="job-actions">
              <a href="${i.meeting_link}" target="_blank" class="btn btn-primary btn-sm" style="text-decoration: none; display: inline-flex; align-items: center; justify-content: center;">Join Meeting</a>
              <button class="btn btn-ghost btn-sm btn-prep-interview" data-round="${i.round_name}">Prepare</button>
              <button class="btn btn-text btn-sm btn-reschedule-interview" data-id="${i.id}">Reschedule</button>
            </div>
          </article>
        `;
      }).join('');
      
      bindInterviewEvents(intGrid);
      
    } catch (err) {
      console.error('Error loading interviews:', err);
    }
  }

  function bindInterviewEvents(container) {
    container.querySelectorAll('.btn-prep-interview').forEach(btn => {
      btn.addEventListener('click', () => {
        alert(`Setting up AI Coach for: ${btn.dataset.round}. Go to the AI Interview Coach card below to start practice questions!`);
        window.location.href = '#coachOrb';
      });
    });
    
    container.querySelectorAll('.btn-reschedule-interview').forEach(btn => {
      btn.addEventListener('click', () => {
        alert("To reschedule your interview, please contact the HR recruiter directly or reply to the email invitation.");
      });
    });
    
    const countdowns = container.querySelectorAll('.countdown[data-target]');
    function updateCountdowns() {
      const now = new Date();
      countdowns.forEach(cd => {
        const target = new Date(cd.dataset.target);
        let diff = Math.max(0, target - now);
        const d = Math.floor(diff / 86400000); diff -= d * 86400000;
        const h = Math.floor(diff / 3600000); diff -= h * 3600000;
        const m = Math.floor(diff / 60000);
        const dEl = cd.querySelector('.cd-d');
        const hEl = cd.querySelector('.cd-h');
        const mEl = cd.querySelector('.cd-m');
        if (dEl) dEl.textContent = String(d).padStart(2, '0');
        if (hEl) hEl.textContent = String(h).padStart(2, '0');
        if (mEl) mEl.textContent = String(m).padStart(2, '0');
      });
    }
    updateCountdowns();
  }

  /* ---------- Render Notifications ---------- */
  function timeAgo(isoString) {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  const NOTIF_LOGO_CLASS = { applied: '', screening: 'teal', shortlisted: '', interview: 'teal', rejected: '', offer: 'teal', tip: 'ai' };

  async function loadNotifications() {
    const list = document.getElementById('notifications-list');
    if (!list) return;

    try {
      const response = await fetch('/career/notifications');
      const notes = await response.json();

      if (!Array.isArray(notes) || notes.length === 0) {
        list.innerHTML = `
          <div style="padding: 20px; text-align: center; color: var(--text-muted);">
            No notifications yet. Apply to jobs and check back — recruiter activity shows up here.
          </div>
        `;
        return;
      }

      list.innerHTML = notes.map(n => {
        const logoClass = NOTIF_LOGO_CLASS[n.type] || '';
        const logoChar = n.type === 'tip' ? '✦' : (n.company_logo || '?');
        return `
          <div class="notif-row ${n.is_read ? '' : 'unread'}" data-id="${n.id}">
            <span class="notif-dot"></span>
            <div class="company-logo sm ${logoClass}">${logoChar}</div>
            <p>${n.message}</p>
            <span class="notif-time">${timeAgo(n.created_at)}</span>
          </div>
        `;
      }).join('');

      list.querySelectorAll('.notif-row.unread').forEach(row => {
        row.addEventListener('click', async () => {
          row.classList.remove('unread');
          try {
            await fetch('/career/notifications/read', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ notification_id: row.dataset.id })
            });
          } catch (err) { console.error(err); }
        }, { once: true });
      });
    } catch (err) {
      console.error('Error loading notifications:', err);
    }
  }

  const markAllReadBtn = document.getElementById('markAllReadBtn');
  if (markAllReadBtn) {
    markAllReadBtn.addEventListener('click', async () => {
      try {
        await fetch('/career/notifications/read', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})
        });
        loadNotifications();
        showToast('All notifications marked as read.');
      } catch (err) {
        console.error(err);
      }
    });
  }

  /* ---------- Event Binders for Job Cards ---------- */
  function bindJobCardEvents(container) {
    container.querySelectorAll('.btn-save').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const jobId = btn.dataset.jobId;
        try {
          const res = await fetch('/career/save-job', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId })
          });
          const data = await res.json();
          if (data.success) {
            btn.textContent = data.action === 'saved' ? '⭐ Saved' : 'Save';
            
            const savedCounter = document.getElementById('hero-saved-jobs-count');
            if (savedCounter) {
              savedCounter.dataset.count = data.saved_jobs_count;
              savedCounter.textContent = data.saved_jobs_count;
            }
            
            loadSavedJobs();
            
            document.querySelectorAll(`.btn-save[data-job-id="${jobId}"]`).forEach(b => {
              b.textContent = data.action === 'saved' ? '⭐ Saved' : 'Save';
            });
            
            showToast(`Job ${data.action === 'saved' ? 'saved to bookmarks' : 'removed from bookmarks'}.`);
          } else if (data.error) {
            showToast(data.error, true);
          }
        } catch (err) {
          console.error(err);
          showToast('Failed to save job.', true);
        }
      });
    });

    container.querySelectorAll('.btn-apply').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const jobId = btn.dataset.jobId;
        try {
          const res = await fetch('/career/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId })
          });
          const data = await res.json();
          if (data.success) {
            btn.textContent = 'Applied';
            btn.disabled = true;
            btn.style.cursor = 'not-allowed';
            btn.style.opacity = '0.6';
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-ghost');
            
            const appCounter = document.getElementById('hero-applications-count');
            if (appCounter) {
              appCounter.dataset.count = data.applications_count;
              appCounter.textContent = data.applications_count;
            }
            
            loadApplications();
            
            document.querySelectorAll(`.btn-apply[data-job-id="${jobId}"]`).forEach(b => {
              b.textContent = 'Applied';
              b.disabled = true;
              b.style.cursor = 'not-allowed';
              b.style.opacity = '0.6';
              b.classList.remove('btn-primary');
              b.classList.add('btn-ghost');
            });
            
            showToast('Application submitted successfully!');
          } else if (data.error) {
            showToast(data.error, true);
          }
        } catch (err) {
          console.error(err);
          showToast('Failed to submit application.', true);
        }
      });
    });
    
    container.querySelectorAll('.btn-details').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const jobId = btn.dataset.jobId;
        const card = container.querySelector(`article[data-job-id="${jobId}"]`);
        if (card) {
          const title = card.querySelector('.job-role').textContent;
          const company = card.querySelector('.job-company').textContent;
          const desc = card.querySelector('.job-desc').textContent;
          alert(`Job Details:\n\nRole: ${title}\nCompany: ${company}\n\nDescription: ${desc}`);
        }
      });
    });
  }

  /* ---------- Toast notification utility ---------- */
  function showToast(message, isError = false) {
    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
      toastContainer = document.createElement('div');
      toastContainer.id = 'toast-container';
      toastContainer.style.position = 'fixed';
      toastContainer.style.bottom = '24px';
      toastContainer.style.right = '24px';
      toastContainer.style.zIndex = '9999';
      toastContainer.style.display = 'flex';
      toastContainer.style.flexDirection = 'column';
      toastContainer.style.gap = '8px';
      document.body.appendChild(toastContainer);
    }
    
    const toast = document.createElement('div');
    toast.style.background = isError ? 'rgba(255, 75, 75, 0.95)' : 'rgba(123, 97, 255, 0.95)';
    toast.style.color = '#fff';
    toast.style.padding = '12px 24px';
    toast.style.borderRadius = '8px';
    toast.style.boxShadow = '0 8px 32px 0 rgba(31, 38, 135, 0.37)';
    toast.style.backdropFilter = 'blur(4px)';
    toast.style.fontSize = '0.9rem';
    toast.style.fontWeight = '500';
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(20px)';
    toast.style.transition = 'all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)';
    toast.textContent = message;
    
    toastContainer.appendChild(toast);
    
    setTimeout(() => {
      toast.style.opacity = '1';
      toast.style.transform = 'translateY(0)';
    }, 10);
    
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(-20px)';
      setTimeout(() => {
        toast.remove();
      }, 300);
    }, 3500);
  }

  /* ---------- Button ripple ---------- */
  document.querySelectorAll('.btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const rect = btn.getBoundingClientRect();
      btn.style.setProperty('--rx', (e.clientX - rect.left) + 'px');
      btn.style.setProperty('--ry', (e.clientY - rect.top) + 'px');
      btn.classList.remove('rippling');
      void btn.offsetWidth;
      btn.classList.add('rippling');
    });
  });

  /* ---------- Page Initial load ---------- */
  async function initPage() {
    try {
      const response = await fetch('/career/jobs');
      const jobs = await response.json();
      renderJobs(jobs);
      renderRecommendedJobs(jobs);
    } catch (err) {
      console.error('Error fetching jobs:', err);
    }
    loadSavedJobs();
    loadApplications();
    loadInterviews();
    loadNotifications();
    loadLatestCoachFeedback();
  }
  
  initPage();

  /* ============================================================
     AI INTERVIEW COACH — real question generation + speech-to-text
     recording + AI scoring (replaces the old static mode-chip /
     record-button stubs).
  ============================================================ */
  const coachState = {
    mode: 'HR Interview',
    questions: [],
    currentIndex: 0,
  };

  const generateQuestionsBtn = document.getElementById('generateQuestionsBtn');
  const recordBtn = document.getElementById('recordBtn');
  const coachQuestionBox = document.getElementById('coachQuestionBox');
  const coachCurrentQuestion = document.getElementById('coachCurrentQuestion');
  const coachStatusMsg = document.getElementById('coachStatusMsg');
  const coachFeedbackTitle = document.getElementById('coachFeedbackTitle');
  const coachFeedbackText = document.getElementById('coachFeedbackText');

  const COACH_CIRCUMFERENCE = 2 * Math.PI * 34; // r=34, matches the radial rings elsewhere

  function animateRadialFill(el, pct) {
    if (!el) return;
    const safePct = Math.max(0, Math.min(100, pct || 0));
    const offset = COACH_CIRCUMFERENCE - (safePct / 100) * COACH_CIRCUMFERENCE;
    el.style.strokeDasharray = COACH_CIRCUMFERENCE;
    el.style.transition = 'stroke-dashoffset 1s cubic-bezier(.16,1,.3,1)';
    requestAnimationFrame(() => { el.style.strokeDashoffset = offset; });
    el.dataset.pct = safePct;
  }

  function renderCoachScores(session) {
    animateRadialFill(document.getElementById('coachScoreOverall'), session.interview_score);
    animateRadialFill(document.getElementById('coachScoreConfidence'), session.confidence);
    animateRadialFill(document.getElementById('coachScoreCommunication'), session.communication);
    animateRadialFill(document.getElementById('coachScoreTechnical'), session.technical_accuracy);

    const overallLabel = document.getElementById('coachScoreOverallLabel');
    const confidenceLabel = document.getElementById('coachScoreConfidenceLabel');
    const communicationLabel = document.getElementById('coachScoreCommunicationLabel');
    const technicalLabel = document.getElementById('coachScoreTechnicalLabel');
    if (overallLabel) overallLabel.textContent = session.interview_score ?? '–';
    if (confidenceLabel) confidenceLabel.textContent = session.confidence ?? '–';
    if (communicationLabel) communicationLabel.textContent = session.communication ?? '–';
    if (technicalLabel) technicalLabel.textContent = session.technical_accuracy ?? '–';

    if (coachFeedbackTitle) {
      coachFeedbackTitle.textContent = session.created_at ? `Feedback — ${session.created_at}` : 'Last Session Feedback';
    }
    if (coachFeedbackText) {
      coachFeedbackText.textContent = session.feedback || 'No feedback text returned.';
    }
  }

  async function loadLatestCoachFeedback() {
    try {
      const res = await fetch('/career/interview-coach/latest');
      const session = await res.json();
      if (session) renderCoachScores(session);
    } catch (err) {
      console.error('Error loading latest interview coach feedback:', err);
    }
  }

  /* ---------- Interview coach mode chips ---------- */
  document.querySelectorAll('.mode-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.mode-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      coachState.mode = chip.dataset.mode || chip.textContent.trim();
      coachState.questions = [];
      coachState.currentIndex = 0;
      if (coachQuestionBox) coachQuestionBox.style.display = 'none';
      if (recordBtn) recordBtn.disabled = true;
      if (coachStatusMsg) coachStatusMsg.textContent = 'Mode changed — generate new questions for this round.';
    });
  });

  /* ---------- Generate Questions ---------- */
  if (generateQuestionsBtn) {
    generateQuestionsBtn.addEventListener('click', async () => {
      generateQuestionsBtn.disabled = true;
      generateQuestionsBtn.textContent = 'Generating…';
      if (coachStatusMsg) coachStatusMsg.textContent = '';

      try {
        const res = await fetch('/career/interview-coach/questions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: coachState.mode })
        });
        const data = await res.json();

        if (data.error) {
          showToast(data.error, true);
          return;
        }

        coachState.questions = data.questions || [];
        coachState.currentIndex = 0;

        if (coachState.questions.length && coachQuestionBox && coachCurrentQuestion) {
          coachQuestionBox.style.display = 'block';
          coachCurrentQuestion.textContent = coachState.questions[0];
          if (recordBtn) recordBtn.disabled = false;
          if (coachStatusMsg) coachStatusMsg.textContent = `Question 1 of ${coachState.questions.length}. Hit Record Answer when ready.`;
        }
      } catch (err) {
        console.error(err);
        showToast('Failed to generate questions.', true);
      } finally {
        generateQuestionsBtn.disabled = false;
        generateQuestionsBtn.textContent = 'Generate Questions';
      }
    });
  }

  /* ---------- Record Answer (Web Speech API speech-to-text) ---------- */
  const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognizer = null;
  let isRecording = false;

  async function submitAnswerForScoring(answerText) {
    const question = coachState.questions[coachState.currentIndex];
    if (coachStatusMsg) coachStatusMsg.textContent = 'Scoring your answer with AI…';

    try {
      const res = await fetch('/career/interview-coach/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: coachState.mode, question, answer_text: answerText })
      });
      const data = await res.json();

      if (data.error) {
        showToast(data.error, true);
        if (coachStatusMsg) coachStatusMsg.textContent = '';
        return;
      }

      renderCoachScores(data);
      showToast('Feedback ready — check your scores.');

      // Advance to the next question in this round, if any.
      coachState.currentIndex += 1;
      if (coachState.currentIndex < coachState.questions.length) {
        coachCurrentQuestion.textContent = coachState.questions[coachState.currentIndex];
        coachStatusMsg.textContent = `Question ${coachState.currentIndex + 1} of ${coachState.questions.length}. Hit Record Answer when ready.`;
      } else {
        coachStatusMsg.textContent = 'Round complete! Generate new questions to keep practicing.';
        if (recordBtn) recordBtn.disabled = true;
      }

      // Analytics' Interview Performance chart now has a fresh data point.
      loadAnalytics();
    } catch (err) {
      console.error(err);
      showToast('Failed to score that answer.', true);
      if (coachStatusMsg) coachStatusMsg.textContent = '';
    }
  }

  function startRecordingUI() {
    isRecording = true;
    recordBtn.classList.add('recording');
    const dot = recordBtn.querySelector('.rec-dot');
    recordBtn.lastChild.textContent = ' Stop Recording';
    if (dot) dot.style.animationDuration = '.7s';
  }

  function stopRecordingUI() {
    isRecording = false;
    recordBtn.classList.remove('recording');
    const dot = recordBtn.querySelector('.rec-dot');
    recordBtn.lastChild.textContent = ' Record Answer';
    if (dot) dot.style.animationDuration = '1.4s';
  }

  if (recordBtn) {
    recordBtn.addEventListener('click', () => {
      if (!coachState.questions.length) {
        showToast('Generate questions first.', true);
        return;
      }

      // ---- Browsers without Web Speech API (e.g. Firefox, Safari) fall
      // back to a typed answer so the feature still works everywhere. ----
      if (!SpeechRecognitionImpl) {
        const typed = prompt('Speech-to-text isn\'t supported in this browser. Type your answer instead:');
        if (typed && typed.trim()) submitAnswerForScoring(typed.trim());
        return;
      }

      if (isRecording) {
        recognizer.stop();
        return;
      }

      recognizer = new SpeechRecognitionImpl();
      recognizer.lang = 'en-IN';
      recognizer.continuous = true;
      recognizer.interimResults = false;

      let transcript = '';
      recognizer.onresult = (event) => {
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            transcript += event.results[i][0].transcript + ' ';
          }
        }
      };
      recognizer.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        showToast('Microphone/speech recognition error: ' + event.error, true);
        stopRecordingUI();
      };
      recognizer.onend = () => {
        stopRecordingUI();
        const finalAnswer = transcript.trim();
        if (finalAnswer) {
          submitAnswerForScoring(finalAnswer);
        } else if (coachStatusMsg) {
          coachStatusMsg.textContent = 'No speech detected — try again.';
        }
      };

      try {
        recognizer.start();
        startRecordingUI();
        if (coachStatusMsg) coachStatusMsg.textContent = 'Listening… click Stop Recording when done.';
      } catch (err) {
        console.error(err);
        showToast('Could not start microphone.', true);
      }
    });
  }

  /* ---------- Countdown timers ---------- */
  const countdowns = document.querySelectorAll('.countdown[data-target]');
  function updateCountdowns(){
    const now = new Date();
    countdowns.forEach(cd => {
      const target = new Date(cd.dataset.target);
      let diff = Math.max(0, target - now);
      const d = Math.floor(diff / 86400000); diff -= d * 86400000;
      const h = Math.floor(diff / 3600000); diff -= h * 3600000;
      const m = Math.floor(diff / 60000);
      const dEl = cd.querySelector('.cd-d');
      const hEl = cd.querySelector('.cd-h');
      const mEl = cd.querySelector('.cd-m');
      if (dEl) dEl.textContent = String(d).padStart(2, '0');
      if (hEl) hEl.textContent = String(h).padStart(2, '0');
      if (mEl) mEl.textContent = String(m).padStart(2, '0');
    });
  }
  updateCountdowns();
  setInterval(updateCountdowns, 60000);

  /* ---------- Mouse parallax on hero orb ---------- */
  const heroSection = document.querySelector('.hero-card');
  const heroOrb = document.getElementById('heroOrb');
  if (heroSection && heroOrb) {
    heroSection.addEventListener('mousemove', (e) => {
      const rect = heroSection.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      heroOrb.style.transform = `translate(${x * 18}px, ${y * 18}px)`;
    });
    heroSection.addEventListener('mouseleave', () => {
      heroOrb.style.transform = 'translate(0,0)';
    });
  }

  /* ---------- Saved jobs carousel drag-to-scroll ---------- */
  const carousel = document.getElementById('savedCarousel');
  if (carousel) {
    let isDown = false, startX, scrollLeft;
    carousel.addEventListener('mousedown', (e) => {
      isDown = true;
      startX = e.pageX - carousel.offsetLeft;
      scrollLeft = carousel.scrollLeft;
      carousel.style.cursor = 'grabbing';
    });
    ['mouseleave', 'mouseup'].forEach(evt =>
      carousel.addEventListener(evt, () => { isDown = false; carousel.style.cursor = 'grab'; })
    );
    carousel.addEventListener('mousemove', (e) => {
      if (!isDown) return;
      e.preventDefault();
      const x = e.pageX - carousel.offsetLeft;
      carousel.scrollLeft = scrollLeft - (x - startX) * 1.5;
    });
  }

  /* ---------- Chart.js — Career Analytics (real data) ---------- */
  const _careerCharts = {};
  function _makeChart(canvasId, config) {
    if (_careerCharts[canvasId]) {
      _careerCharts[canvasId].destroy();
    }
    _careerCharts[canvasId] = new Chart(document.getElementById(canvasId), config);
    return _careerCharts[canvasId];
  }

  async function loadAnalytics() {
    if (!window.Chart) return;

    Chart.defaults.color = '#9A9AB8';
    Chart.defaults.font.family = 'Inter, sans-serif';

    const gridColor = 'rgba(42,42,74,0.6)';
    const purple = '#7B61FF';
    const teal = '#00D4AA';

    const commonGrid = {
      x: { grid: { color: gridColor }, ticks: { font: { size: 11 } } },
      y: { grid: { color: gridColor }, ticks: { font: { size: 11 } } }
    };

    let analytics;
    try {
      const res = await fetch('/career/analytics');
      analytics = await res.json();
    } catch (err) {
      console.error('Error loading analytics:', err);
      return;
    }
    if (analytics.error) return;

    _makeChart('chartSuccess', {
      type: 'bar',
      data: {
        labels: analytics.success_rate.labels,
        datasets: [{
          label: 'Success Rate %',
          data: analytics.success_rate.data,
          backgroundColor: purple,
          borderRadius: 8,
          maxBarThickness: 28
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: commonGrid,
        animation: { duration: 1200, easing: 'easeOutCubic' }
      }
    });

    _makeChart('chartInterview', {
      type: 'line',
      data: {
        labels: analytics.interview_performance.labels.length ? analytics.interview_performance.labels : ['No sessions yet'],
        datasets: [{
          label: 'Score',
          data: analytics.interview_performance.data.length ? analytics.interview_performance.data : [0],
          borderColor: teal,
          backgroundColor: 'rgba(0,212,170,0.12)',
          fill: true,
          tension: 0.4,
          pointBackgroundColor: teal,
          pointRadius: 4
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: commonGrid,
        animation: { duration: 1200, easing: 'easeOutCubic' }
      }
    });

    _makeChart('chartSkills', {
      type: 'line',
      data: {
        labels: analytics.skills_growth.labels.length ? analytics.skills_growth.labels : ['No history yet'],
        datasets: [{
          label: 'Skills Tracked',
          data: analytics.skills_growth.data.length ? analytics.skills_growth.data : [0],
          borderColor: purple,
          backgroundColor: 'rgba(123,97,255,0.18)',
          fill: true,
          tension: 0.35,
          pointBackgroundColor: purple,
          pointRadius: 4
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: commonGrid,
        animation: { duration: 1200, easing: 'easeOutCubic' }
      }
    });

    _makeChart('chartMatch', {
      type: 'line',
      data: {
        labels: analytics.job_match_trend.labels.length ? analytics.job_match_trend.labels : ['No applications yet'],
        datasets: [{
          label: 'Match % at Apply',
          data: analytics.job_match_trend.data.length ? analytics.job_match_trend.data : [0],
          borderColor: teal,
          backgroundColor: 'rgba(0,212,170,0.1)',
          fill: true,
          tension: 0.4,
          pointBackgroundColor: teal,
          pointRadius: 3
        },
        {
          label: 'Current Profile Match %',
          data: new Array((analytics.job_match_trend.labels.length || 1)).fill(analytics.job_match_trend.current_avg_match),
          borderColor: purple,
          backgroundColor: 'transparent',
          borderDash: [5, 4],
          tension: 0.4,
          pointRadius: 0
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: true, labels: { boxWidth: 10, font: { size: 10.5 } } } },
        scales: commonGrid,
        animation: { duration: 1200, easing: 'easeOutCubic' }
      }
    });
  }
  loadAnalytics();

  /* ---------- Talk to Cara — real /api/chat integration ---------- */
  const caraBtn = document.getElementById('talkToCaraBtn');
  if (caraBtn) {
    let panel = null;

    function buildPanel(){
      panel = document.createElement('div');
      panel.className = 'cara-panel glass';
      panel.innerHTML = `
        <div class="cara-panel-head">
          <span>✦ Talk to Cara</span>
          <button class="cara-close" aria-label="Close">✕</button>
        </div>
        <div class="cara-messages"></div>
        <form class="cara-input-row">
          <input type="text" placeholder="Ask Cara anything about your career..." autocomplete="off" required>
          <button type="submit" class="btn btn-primary btn-sm">Send</button>
        </form>
      `;
      document.body.appendChild(panel);

      panel.querySelector('.cara-close').addEventListener('click', () => panel.remove());

      const messages = panel.querySelector('.cara-messages');
      const form = panel.querySelector('.cara-input-row');
      const input = form.querySelector('input');

      function addMessage(text, who){
        const row = document.createElement('div');
        row.className = 'cara-msg ' + who;
        row.textContent = text;
        messages.appendChild(row);
        messages.scrollTop = messages.scrollHeight;
      }

      addMessage("Hi, I'm Cara. Ask me about roles, resumes, interviews, or anything career-related.", 'bot');

      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const question = input.value.trim();
        if (!question) return;
        addMessage(question, 'user');
        input.value = '';
        addMessage('Thinking…', 'bot pending');

        try {
          const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question })
          });
          const data = await res.json();
          const pending = messages.querySelector('.pending');
          if (pending) pending.remove();
          if (data.error) {
            addMessage(data.error, 'bot error');
          } else {
            addMessage(data.output || "Sorry, I couldn't generate a response.", 'bot');
          }
        } catch (err) {
          const pending = messages.querySelector('.pending');
          if (pending) pending.remove();
          addMessage('Network error reaching Cara. Please try again.', 'bot error');
        }
      });
    }

    caraBtn.addEventListener('click', () => {
      if (!panel) buildPanel();
    });
  }

});
