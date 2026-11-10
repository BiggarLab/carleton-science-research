"""The entry screen for the static pages: a notice every visitor has to accept, plus a cosmetic password box.
The password keeps casual visitors out; it does not protect the data files.
The password's hash lives in docs/gate.json, written by the 'Set site password' action from the SITE_PASSWORD secret."""

SALT = "carleton-research-dashboard"


ACK_DAYS = 30  # how long a browser remembers that the notice was accepted

NOTICE = (
    "<b>Before you continue</b>"
    "<p>This is an independent tool. It is not affiliated with, endorsed by, or an official publication of Carleton University.</p>"
    "<ul>"
    "<li>It is built only from public sources (OpenAlex, the NSERC and SSHRC awards databases, public patent records). No internal university data is used.</li>"
    "<li>The data is collected and matched to people automatically. It can be incomplete, out of date or wrong: papers and grants can be missed, and coverage differs between fields.</li>"
    "<li>Summaries, opportunity notes and assistant answers are written by AI and can contain errors. Check the original source.</li>"
    "<li>It is meant for exploring research activity and finding expertise. It should not be used for decision making.</li>"
    "</ul>"
)


def gate_html(root=""):
    """Snippet for <head>: a notice every visitor has to accept, plus the password box when a password is set.
    root is the relative path from the page to the site root, e.g. '' or '../'."""
    q = lambda v: repr(v).replace("'", '"')
    return """<style>html.gated body>*:not(#gate){visibility:hidden}#gate{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;overflow:auto;padding:16px;box-sizing:border-box;
background:#f3f4f6;font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;color:#15171c}#gate form{background:#fff;border:1px solid #d9dce1;border-radius:6px;padding:22px;margin:auto;
width:min(520px,100%);box-sizing:border-box;display:flex;flex-direction:column;gap:10px}#gate p,#gate ul{margin:0}#gate ul{padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:14px}
#gate label{font-weight:600;margin-top:4px}#gate input{padding:8px 10px;border:1px solid #d9dce1;border-radius:4px;font:inherit}
#gate button{padding:9px;border:0;border-radius:4px;background:#15171c;color:#fff;font:inherit;cursor:pointer;margin-top:4px}#gate small{color:#b0162b;min-height:1em}
@media (prefers-color-scheme:dark){#gate{background:#111316;color:#eceef1}#gate form{background:#191c20;border-color:#2e3238}#gate input{background:#111316;color:#eceef1;border-color:#2e3238}#gate button{background:#eceef1;color:#111316}}</style>
<script>(function(){var R=""" + q(root) + """,K="cs-gate",A="cs-ack",S=""" + q(SALT) + """,T=""" + str(ACK_DAYS) + """*864e5,N=""" + q(NOTICE) + """,d=document.documentElement;d.classList.add("gated");
function open(){d.classList.remove("gated");var g=document.getElementById("gate");if(g)g.remove();}
async function h(t){var b=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(S+t));return Array.from(new Uint8Array(b)).map(function(x){return x.toString(16).padStart(2,"0")}).join("");}
fetch(R+"gate.json",{cache:"no-store"}).then(function(r){return r.ok?r.json():null}).catch(function(){return null}).then(function(g){
 var want=g&&g.sha256;var have="",ack=0;try{have=localStorage.getItem(K)||"";ack=+localStorage.getItem(A)||0}catch(e){}
 var pw=!!want&&have!==want,ok=Date.now()-ack<T;
 if(!pw&&ok)return open();
 var show=function(){var w=document.createElement("div");w.id="gate";w.setAttribute("role","dialog");w.setAttribute("aria-modal","true");
  w.innerHTML="<form>"+N+(pw?'<label for="gate-pw">Password</label><input id="gate-pw" type="password" autocomplete="current-password">':"")+"<button>I understand, continue</button><small></small></form>";
  document.body.appendChild(w);var f=w.querySelector("form"),i=w.querySelector("input");(i||w.querySelector("button")).focus();
  f.onsubmit=async function(e){e.preventDefault();
   if(pw){var x=await h(i.value);if(x!==want){w.querySelector("small").textContent="That password did not work.";i.select();return;}try{localStorage.setItem(K,x)}catch(e){}}
   try{localStorage.setItem(A,String(Date.now()))}catch(e){}open();};};
 if(document.body)show();else document.addEventListener("DOMContentLoaded",show);});})();</script>"""


if __name__ == "__main__":
    import hashlib, json, os, sys
    from pathlib import Path
    pw = os.environ.get("SITE_PASSWORD", "")
    out = Path(__file__).resolve().parent.parent / "docs/gate.json"
    out.write_text(json.dumps({"sha256": hashlib.sha256((SALT + pw).encode()).hexdigest()} if pw else {}) + "\n")
    print("site password", "set" if pw else "removed (no SITE_PASSWORD secret)")
