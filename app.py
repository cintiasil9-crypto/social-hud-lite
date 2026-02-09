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
# NEGATORS (FIXED – WAS CAUSING 500)
# =================================================

NEGATORS = {
    "not","no","never","dont","don't","cant","can't",
    "isnt","isn't","wasnt","wasn't",
    "aint","ain't","nah","nope","naw",
    "idk","idc","dont care","doesnt matter"
}

# =================================================
# KEYWORDS
# =================================================

ENGAGING = {"hi","hey","hello","yo","sup","welcome","hiya"}
CURIOUS  = {"why","how","what","where","when","who","?"}
HUMOR    = {"lol","lmao","haha","😂","🤣","😆"}
SUPPORT  = {"sorry","hope","ok","hug","hugs","<3"}
DOMINANT = {"listen","stop","wait","now","do it"}
COMBATIVE= {"stfu","wtf","idiot","shut","fuck"}

FLIRTY   = {"cute","hot","sexy","kiss","mwah","😘","😍"}
SEXUAL   = {"sex","horny","naked","fuck"}
CURSE    = {"fuck","shit","damn","wtf"}

# =================================================
# SUMMARY PHRASES (LITE)
# =================================================

PROFILE_PHRASES = {
    "engaging": "Naturally pulls people into conversation",
    "curious": "Pays attention to who’s around",
    "humorous": "Keeps things light and playful",
    "supportive": "Creates emotional safety",
    "dominant": "Takes social initiative",
    "combative": "Pushes back when challenged"
}

ROOM_VIBES = [
    "Calm, low-pressure energy",
    "Light social buzz",
    "Conversation-friendly",
    "Mixed personalities, steady flow",
    "Active but not chaotic"
]

NEARBY_TAKES = [
    "A few different personalities nearby",
    "Small group energy forming",
    "People are watching before engaging",
    "Low noise, open vibe",
    "Social mix looks approachable"
]

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
# BUILD PROFILES (LITE)
# =================================================

def build_profiles():
    if CACHE["profiles"] and time.time() - CACHE["ts"] < CACHE_TTL:
        return CACHE["profiles"]

    rows = fetch_rows()
    profiles = {}

    for r in rows:
        uid = r.get("avatar_uuid")
        if not uid:
            continue

        ts = float(r.get("timestamp", NOW))
        w = decay(ts)

        p = profiles.setdefault(uid, {
            "uuid": uid,
            "name": r.get("display_name", "Unknown"),
            "messages": 0,
            "traits": defaultdict(float),
            "recent": 0
        })

        msgs = max(int(r.get("messages", 1)), 1)
        p["messages"] += msgs * w
        if NOW - ts < 3600:
            p["recent"] += msgs

        hits = extract_hits(r.get("context_sample", ""))
        for k,v in hits.items():
            p["traits"][k] += v * w

    out = []
    for p in profiles.values():
        m = max(p["messages"],1)
        conf = min(1.0, math.log(m+1)/4)

        top_trait = max(p["traits"], key=p["traits"].get, default=None)

        out.append({
            "uuid": p["uuid"],
            "name": p["name"],
            "confidence": int(conf*100),
            "recent": p["recent"],
            "top_trait": top_trait
        })

    CACHE["profiles"] = out
    CACHE["ts"] = time.time()
    return out

# =================================================
# PRESENTATION (LITE – DYNAMIC)
# =================================================

def present_profile(p):
    if not p:
        return "No profile data yet.\nMore activity sharpens the read."

    line = PROFILE_PHRASES.get(p["top_trait"], "Social patterns still forming")

    return (
        "My Profile (Lite)\n"
        f"• Social read: {line}\n"
        f"• Confidence signal: {p['confidence']}%\n\n"
        "Upgrade unlocks full trait breakdown."
    )

def present_nearby(profiles):
    if not profiles:
        return "Nearby (Lite)\n• No readable activity yet."

    vibe = NEARBY_TAKES[len(profiles) % len(NEARBY_TAKES)]

    names = ", ".join(p["name"] for p in profiles[:3])

    return (
        "Nearby (Lite)\n"
        f"• {vibe}\n"
        f"• Notable nearby: {names}\n\n"
        "Tap a name for a quick read."
    )

def present_room_vibe(profiles):
    vibe = ROOM_VIBES[len(profiles) % len(ROOM_VIBES)]

    return (
        "Room Vibe (Lite)\n"
        f"• {vibe}\n\n"
        "Full version shows live analytics."
    )

# =================================================
# ENDPOINTS
# =================================================

@app.route("/profile/self", methods=["POST"])
def profile_self():
    uuid = (request.get_json(silent=True) or {}).get("uuid")
    profiles = build_profiles()
    me = next((p for p in profiles if p["uuid"] == uuid), None)
    return jsonify({"text": present_profile(me)})

@app.route("/profile/lookup", methods=["POST"])
def profile_lookup():
    name = (request.get_json(silent=True) or {}).get("name")
    profiles = build_profiles()
    p = next((p for p in profiles if p["name"] == name), None)
    return jsonify({"text": present_profile(p)})

@app.route("/room/vibe", methods=["POST"])
def room_vibe():
    profiles = build_profiles()
    return jsonify({"text": present_room_vibe(profiles)})

@app.route("/")
def ok():
    return "OK", 200
