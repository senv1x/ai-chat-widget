"""BrightSmile Dental AI assistant: demo backend (Python stdlib only).

- GET  /              -> static demo site with chat widget (public/)
- POST /api/chat      -> {"message": "..."} -> answer grounded in data/faq.json
- POST /api/lead      -> {"name","email","phone","note"} -> appended to data/leads.csv
- GET  /api/leads.csv -> download the leads file (Google Sheets: File > Import)

LLM mode: set OPENAI_API_KEY (optional OPENAI_MODEL) and answers are generated
from the FAQ context only. Without a key, a deterministic keyword-retrieval
"mock LLM" answers from the same FAQ, so the demo runs anywhere.
"""
import csv, json, os, re, datetime, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
FAQ = json.load(open(os.path.join(ROOT, "data", "faq.json")))
LEADS = os.path.join(ROOT, "data", "leads.csv")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HANDOFF = ("I'm not 100% sure about that one, so I don't want to guess. "
           "Leave your name, email and phone and a team member will get back to you.")


def retrieve(msg):
    words = set(re.findall(r"[a-z\-]+", msg.lower()))
    scored = [(len(words & set(f["keywords"])), f) for f in FAQ["faqs"]]
    scored.sort(key=lambda x: -x[0])
    return [f for s, f in scored if s > 0][:3]


def mock_llm(msg, hits):
    if re.search(r"\b(hi|hello|hey)\b", msg.lower()) and not hits:
        return {"answer": "Hi! I'm the BrightSmile assistant. Ask me about hours, prices, insurance or booking.", "handoff": False}
    if not hits:
        return {"answer": HANDOFF, "handoff": True}
    return {"answer": hits[0]["a"], "handoff": False,
            "lead_prompt": any(k in msg.lower() for k in ["book", "appointment", "pain", "emergency", "price", "cost", "much", "toothache"])}


def openai_llm(msg, hits):
    ctx = "\n".join(f"Q: {f['q']}\nA: {f['a']}" for f in (hits or FAQ["faqs"]))
    body = {"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0.2, "messages": [
        {"role": "system", "content": "You are the website assistant for a dental clinic. Answer ONLY from the context. "
         "If the context does not contain the answer, reply exactly: HANDOFF. Keep answers under 60 words.\n\n" + ctx},
        {"role": "user", "content": msg}]}
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"], "Content-Type": "application/json"})
    text = json.load(urllib.request.urlopen(req, timeout=20))["choices"][0]["message"]["content"].strip()
    if text.startswith("HANDOFF"):
        return {"answer": HANDOFF, "handoff": True}
    return {"answer": text, "handoff": False}


def answer(msg):
    hits = retrieve(msg)
    if os.getenv("OPENAI_API_KEY"):
        try:
            r = openai_llm(msg, hits); r["mode"] = "openai"; return r
        except Exception as e:  # fall back, never break the widget
            print("LLM error, falling back to mock:", e)
    r = mock_llm(msg, hits); r["mode"] = "mock"; return r


def save_lead(d):
    name, email, phone = (d.get(k, "").strip() for k in ("name", "email", "phone"))
    if not name or not EMAIL_RE.match(email):
        return False, "Please add your name and a valid email."
    new = not os.path.exists(LEADS)
    with open(LEADS, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["created_at", "name", "email", "phone", "note", "source"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), name, email, phone,
                    d.get("note", "")[:500], "website-chat"])
    print(f"NEW LEAD: {name} <{email}> {phone}")  # swap for email/Slack/Sheets webhook in production
    return True, "Thanks! The front desk will contact you shortly."


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=os.path.join(ROOT, "public"), **k)

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/leads.csv":
            data = open(LEADS, "rb").read() if os.path.exists(LEADS) else b""
            self.send_response(200); self.send_header("Content-Type", "text/csv")
            self.end_headers(); return self.wfile.write(data)
        return super().do_GET()

    def do_POST(self):
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self._json(400, {"error": "bad json"})
        if self.path == "/api/chat":
            return self._json(200, answer(str(d.get("message", ""))[:1000]))
        if self.path == "/api/lead":
            ok, msg = save_lead(d)
            return self._json(200 if ok else 400, {"ok": ok, "message": msg})
        self._json(404, {"error": "not found"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8081))
    print(f"BrightSmile demo on http://localhost:{port}  (mode: {'openai' if os.getenv('OPENAI_API_KEY') else 'mock'})")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
