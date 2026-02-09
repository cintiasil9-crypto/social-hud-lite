from flask import Flask, Response, jsonify, request
import os, time, math, requests, json, re
from collections import defaultdict

# =================================================
# APP SETUP
# =================================================

app = Flask(__name__)
GOOGLE_PROFILES_FEED = os.environ["GOOGLE_PROFILES_FEED"]

CACHE = {"profiles": None, "ts": 0}
CACHE_TTL = 300
NOW = time.time()

# =================================================
# WEIGHTS (SAME AS FULL)
# =================================================

TRAIT_WEIGHTS = {
    "engaging":   1.0,
    "curious":    0.9,
    "humorous":   1.2,
    "supportive": 1.1,
    "dominant":   1.0,
    "combative":  1.4,
}

STYLE_WEIGHTS = {
    "flirty": 1.0,
    "sexual": 1.2,
    "curse":  0.9
}

# =================================================
# KEYWORDS (FULL PARITY)
# =================================================

ENGAGING = {"hi","hey","heya","hiya","yo","sup","wb","welcome","hello","ello","hai","hii","o/","\\o","wave","waves"}
CURIOUS  = {"why","how","what","where","when","who","anyone","anybody","?","??","huh","hmm"}
HUMOR    = {"lol","lmao","rofl","haha","😂","🤣","😆","💀"}
SUPPORT  = {"sorry","hope","ok","okay","np","hug","hugs","<3","❤️"}
DOMINANT = {"listen","look","stop","wait","now","do it","move","sit","stand"}
COMBATIVE= {"idiot","stupid","dumb","shut","stfu","wtf","bs"}

FLIRTY   = {"cute","hot","pretty","handsome","sexy","kiss","mwah","😘","😉"}
SEXUAL   = {"sex","fuck","horny","naked","hard","wet"}
CURSE    = {"fuck","shit","damn","bitch","asshole"}

NEGATORS = {"not","no","never","dont","don't","cant","can't","nah","nope","aint"}

# =================================================
# SUMMARY PHRASES (FULL COPY)
# =================================================

PRIMARY_PHRASE = {
    "engaging": "Naturally pulls people into conversation",
    "curious": "Actively curious about who’s around",
    "humorous": "Shows up to entertain",
    "supportive": "Creates emotional safety",
    "dominant": "Carries main-character energy",
    "combative": "Thrives on strong opinions",
}

SECONDARY_PHRASE = {
    "engaging": "keeps interactions flowing",
    "curious": "asks thoughtful questions",
    "humorous": "keeps things playful",
    "supportive": "softens heavy moments",
    "dominant": "steers conversations",
    "combative": "pushes back when challenged",
}

TERTIARY_PHRASE = {
    "engaging": "without forcing attention",
    "curious": "while quietly observing",
    "humorous": "often with a playful edge",
    "supportive": "in a grounding way",
    "dominant": "with subtle authority",
    "combative": "with occasional friction",
}

MODIFIER_PHRASE = {
    ("curious","flirty"): "with light romantic curiosity",
    ("humorous","flirty"): "through playful flirtation",
    ("supportive","flirty"): "with warm, gentle flirtation",
    ("dominant","flirty"): "with confident flirtation",
    ("curious","sexual"): "with adult curiosity",
    ("supportive","sexual"): "with emotional intimacy and adult undertones",
    ("dominant","sexual"): "with bold, adult energy",
    ("humorous","sexual"): "using shock humor",
    ("humorous","curse"): "with crude humor",
    ("dominant","curse"): "in a forceful, unfiltered way",
    ("supportive","curse"): "in a familiar, casual tone",
}

# =================================================
# HELPERS
# =================================================

def decay(ts):
    age = (NOW - ts) / 3600
    if age <= 1: return 1.0
    if age <= 24: return 0.7
    return 0.4

def extract_hits(text):
    hits = defaultdict(int)
    if not text:
        return hits

    words = re.findall(r"\b\w+\b", text.lower())

    def neg(i):
        return any(w in NEGATORS for w in words[max(0,i-3):i])

    for i,w in enumerate(words):
        if neg(i): continue
        if w in ENGAGING: hits["engaging"] += 1
        if w in CURIOUS: hits["curious"] += 1
        if w in HUMOR: hits["humorous"] += 1
        if w in SUPPORT: hits["supportive"] += 1
        if w in DOMINANT: hits["dominant"] += 1
        if w in COMBATIVE: hits["combative"] += 1
        if w in FLIRTY: hits["flirty"] += 1
        if w in SEXUAL: hits["sexual"] += 1
        if w in CURSE: hits["curse"] += 1

    return hits

# =================================================
# DATA FETCH
# =================================================

def fetch_rows():
    r = requests.get(GOOGLE_PROFILES_FEED, timeout=20)
    m = re.search(r"setResponse\((\{.*\})\)", r.text, re.S)
    payload = json.loads(m.group(1))
    cols = [c["label"] for c in payload["table"]["cols"]]

    rows = []
    for row in payload["table"]["rows"]:
        rec = {}
        for i, cell in enumerate(row["c"]):
            rec[cols[i]] = cell["v"] if cell else 0
        rows.append(rec)
    return rows

# =================================================
# SUMMARY ENGINE (UNCHANGED)
# =================================================

def build_summary(conf, traits, styles):
    if conf < 0.25:
        return "Barely spoke. Vibes pending."

    ranked = sorted(traits.items(), key=lambda x:x[1], reverse=True)
    top = [k for k,v in ranked if v > 0][:3]

    if not top:
        return "Present, but patterns are still forming."

    if len(top) == 1:
        return PRIMARY_PHRASE[top[0]] + ". This trait stands out strongly, but there isn’t enough data yet to assess other aspects."

    base = ", ".join([
        PRIMARY_PHRASE[top[0]],
        SECONDARY_PHRASE[top[1]],
        TERTIARY_PHRASE[top[2]] if len(top) > 2 else ""
    ]).strip(", ") + "."

    for m in ["sexual","flirty","curse"]:
        if styles.get(m,0) >= 0.2 and conf >= 0.35:
            phrase = MODIFIER_PHRASE.get((top[0], m))
            if phrase:
                return base + " " + phrase + "."

    return base

# =================================================
# BUILD PROFILES (FULL LOGIC, LITE USE)
# =================================================

def build_profiles():
    if CACHE["profiles"] and time.time() - CACHE["ts"] < CACHE_TTL:
        return CACHE["profiles"]

    rows = fetch_rows()
    profiles = {}

    for r in rows:
        uid = r.get("avatar_uuid")
        if not uid: continue

        ts = float(r.get("timestamp", NOW))
        w = decay(ts)

        p = profiles.setdefault(uid, {
            "avatar_uuid": uid,
            "name": r.get("display_name","Unknown"),
            "messages": 0,
            "raw_traits": defaultdict(float),
            "raw_styles": defaultdict(float),
            "recent": 0
        })

        msgs = max(int(r.get("messages",1)),1)
        p["messages"] += msgs * w
        if NOW - ts < 3600:
            p["recent"] += msgs

        hits = extract_hits(r.get("context_sample",""))

        for k,v in hits.items():
            if k in TRAIT_WEIGHTS:
                p["raw_traits"][k] += v * TRAIT_WEIGHTS[k] * w
            if k in STYLE_WEIGHTS:
                p["raw_styles"][k] += v * STYLE_WEIGHTS[k] * w

    out = []

    for p in profiles.values():
        m = max(p["messages"],1)
        conf = min(1.0, math.log(m+1)/4)
        damp = max(0.05, conf ** 1.5)

        traits = {k:min((p["raw_traits"][k]/m)*damp,1.0) for k in TRAIT_WEIGHTS}
        styles = {k:min((p["raw_styles"][k]/(m*0.3))*damp,1.0) for k in STYLE_WEIGHTS}

        out.append({
            "avatar_uuid": p["avatar_uuid"],
            "name": p["name"],
            "confidence": int(conf*100),
            "recent": p["recent"],
            "traits": traits,
            "styles": styles,
            "summary": build_summary(conf, traits, styles)
        })

    CACHE["profiles"] = out
    CACHE["ts"] = time.time()
    return out

# =================================================
# LITE PRESENTATION
# =================================================

def conf_label(c):
    if c >= 70: return "Strong presence"
    if c >= 40: return "Steady presence"
    return "Emerging presence"

def lite_profile(p):
    return (
        "🧠 My Profile (Lite)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 {p['name']}\n"
        f"✨ {conf_label(p['confidence'])}\n\n"
        "🔍 Social read:\n"
        f"{p['summary']}\n\n"
        "🔓 Upgrade to unlock full analytics."
    )

def lite_nearby(profiles):
    lines = [
        "👥 Nearby (Lite)",
        "━━━━━━━━━━━━━━━━━━━━"
    ]
    for p in profiles[:6]:
        lines.append(f"• {p['name']} — {conf_label(p['confidence'])}")
    lines.append("\nTap a name to view profile.")
    return "\n".join(lines)

def lite_room_vibe(profiles):
    active = sum(1 for p in profiles if p["recent"] > 0)
    vibe = "Active" if active >= 4 else "Warming up" if active >= 2 else "Calm"
    return (
        "🌙 Room Vibe (Lite)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🎭 Overall energy: {vibe}\n\n"
        "Easy room to step into."
    )

# =================================================
# ENDPOINTS (LITE)
# =================================================

@app.route("/profile/self", methods=["POST"])
def profile_self():
    uuid = (request.get_json(silent=True) or {}).get("uuid")
    for p in build_profiles():
        if p["avatar_uuid"] == uuid:
            return Response(json.dumps({"text": lite_profile(p)}, ensure_ascii=False),
                            mimetype="application/json; charset=utf-8")
    return jsonify({"error":"profile not found"}),404

@app.route("/profile/lookup", methods=["POST"])
def profile_lookup():
    name = (request.get_json(silent=True) or {}).get("name")
    for p in build_profiles():
        if p["name"].strip().lower() == name.strip().lower():
            return Response(json.dumps({"text": lite_profile(p)}, ensure_ascii=False),
                            mimetype="application/json; charset=utf-8")
    return jsonify({"error":"profile not found"}),404

@app.route("/room/vibe", methods=["POST"])
def room_vibe():
    uuids = set((request.get_json(silent=True) or {}).get("uuids", []))
    profiles = [p for p in build_profiles() if p["avatar_uuid"] in uuids]
    return Response(json.dumps({"text": lite_room_vibe(profiles)}, ensure_ascii=False),
                    mimetype="application/json; charset=utf-8")

@app.route("/profiles/available", methods=["POST"])
def profiles_available():
    uuids = set((request.get_json(silent=True) or {}).get("uuids", []))
    return Response(json.dumps(
        [{"name":p["name"],"uuid":p["avatar_uuid"]} for p in build_profiles() if p["avatar_uuid"] in uuids],
        ensure_ascii=False),
        mimetype="application/json; charset=utf-8")

@app.route("/")
def ok():
    return "OK", 200
