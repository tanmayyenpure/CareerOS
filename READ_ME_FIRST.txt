CareerOS fix — Learning Hub & Coding Arena blank-page issue
=============================================================

WHAT'S IN THIS ZIP
  templates/learning-hub.html   -> replaces your templates/learning-hub.html
  templates/coding-arena.html   -> replaces your templates/coding-arena.html
  static/css/learning-hub.css   -> replaces your static/css/learning-hub.css
  static/css/coding-arena.css   -> replaces your static/css/coding-arena.css
  static/js/chatbot-widget.js   -> only needed if you don't already have this file

DEPLOY (exact steps)
  1. Copy each file to the EXACT path shown above, inside your project root
     (the same folder as app.py — currently:
     C:\Users\91703\OneDrive\Documents\CareerOS\)
     Overwrite when prompted. Do not rename, do not save as a copy.

  2. Stop Flask completely (Ctrl+C in the terminal) and start it again.
     A browser refresh alone is not enough if Flask cached the template.

  3. Hard-refresh the browser tab: Ctrl+Shift+R (Windows/Linux) or
     Cmd+Shift+R (Mac). Do this on both /learning-hub and /coding-arena.

WHY YOUR LAST ATTEMPT LIKELY DIDN'T TAKE EFFECT
  Your server log showed:
    GET /static/css/learning-hub.css HTTP/1.1" 304
  A 304 means Flask told the browser "this file hasn't changed since you
  last saw it" — which only happens if the file's timestamp on disk is
  identical to before. That strongly suggests the previous replacement
  either saved to the wrong location or never overwrote the original.

  To make sure this can't happen silently again, the CSS links in these
  new HTML files now include a version tag (?v=fix2). That forces the
  browser to treat it as a brand-new URL it has never cached, regardless
  of what happened before — so if it's still blank after this, the file
  genuinely isn't reaching the browser, and the problem is 100% in the
  deploy step (wrong path / Flask not restarted / a second copy of the
  project running), not in the code itself.

ONE-LINE VERIFICATION (does the fix actually load?)
  After restarting Flask, open this URL directly in your browser:
    http://127.0.0.1:5000/static/css/learning-hub.css?v=fix2
  Press Ctrl+F and search for the word "reveal".
  You should see:
    .reveal{ opacity:1; transform:none; }
  If instead you see "opacity:0" here, the new file did not get copied
  to the right place — check that this exact URL's file is the one you
  just replaced, and that there isn't a second CareerOS folder/venv
  Flask might be running from instead.

WHAT script.js IS (seen in your server log, not part of this fix)
  Your log shows a file called static/js/script.js loading on every
  page. That file was never uploaded to me, so it wasn't touched by any
  of these fixes. It's worth checking what it does — if it manipulates
  opacity, theme, or animation classes anywhere, it could be interacting
  with the .reveal elements independently of everything patched here.
