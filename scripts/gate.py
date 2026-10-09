"""A cosmetic password screen for the static pages. It keeps casual visitors out; it does not protect the data files.
The password's hash lives in docs/gate.json, written by the 'Set site password' action from the SITE_PASSWORD secret."""

SALT = "carleton-research-dashboard"


def gate_html(root=""):
    """Snippet for <head>. root is the relative path from the page to the site root, e.g. '' or '../'."""
    return """<style>html.gated body>*:not(#gate){visibility:hidden}#gate{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;
background:#f3f4f6;font:15px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;color:#15171c}#gate form{background:#fff;border:1px solid #d9dce1;border-radius:6px;padding:22px;
width:min(340px,calc(100vw - 32px));display:flex;flex-direction:column;gap:10px}#gate input{padding:8px 10px;border:1px solid #d9dce1;border-radius:4px;font:inherit}
#gate button{padding:8px;border:0;border-radius:4px;background:#15171c;color:#fff;font:inherit;cursor:pointer}#gate small{color:#b0162b;min-height:1em}
@media (prefers-color-scheme:dark){#gate{background:#111316;color:#eceef1}#gate form{background:#191c20;border-color:#2e3238}#gate input{background:#111316;color:#eceef1;border-color:#2e3238}#gate button{background:#eceef1;color:#111316}}</style>
<script>(function(){var R=""" + repr(root).replace("'", '"') + """,K="cs-gate",S=""" + repr(SALT).replace("'", '"') + """,d=document.documentElement;d.classList.add("gated");
function open(){d.classList.remove("gated");var g=document.getElementById("gate");if(g)g.remove();}
async function h(t){var b=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(S+t));return Array.from(new Uint8Array(b)).map(function(x){return x.toString(16).padStart(2,"0")}).join("");}
fetch(R+"gate.json",{cache:"no-store"}).then(function(r){return r.ok?r.json():null}).catch(function(){return null}).then(function(g){
 var want=g&&g.sha256;var have="";try{have=localStorage.getItem(K)||""}catch(e){}
 if(!want||have===want)return open();
 var show=function(){var w=document.createElement("div");w.id="gate";w.innerHTML='<form><b>Password</b><input type="password" autocomplete="current-password" aria-label="Password" autofocus><button>Open</button><small></small></form>';
  document.body.appendChild(w);var f=w.querySelector("form"),i=w.querySelector("input");i.focus();
  f.onsubmit=async function(e){e.preventDefault();var x=await h(i.value);if(x===want){try{localStorage.setItem(K,x)}catch(e){}open();}else{w.querySelector("small").textContent="That password didn't work.";i.select();}};};
 if(document.body)show();else document.addEventListener("DOMContentLoaded",show);});})();</script>"""


if __name__ == "__main__":
    import hashlib, json, os, sys
    from pathlib import Path
    pw = os.environ.get("SITE_PASSWORD", "")
    out = Path(__file__).resolve().parent.parent / "docs/gate.json"
    out.write_text(json.dumps({"sha256": hashlib.sha256((SALT + pw).encode()).hexdigest()} if pw else {}) + "\n")
    print("site password", "set" if pw else "removed (no SITE_PASSWORD secret)")
