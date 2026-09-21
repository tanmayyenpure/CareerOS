"""
network_routes.py
------------------
Blueprint for the LinkedIn-style networking features: connections, invitations,
company follows, and public profile viewing.

HOW TO WIRE THIS INTO YOUR APP
  from network_routes import network_bp
  app.register_blueprint(network_bp)

Everything here uses in-memory mock data (MOCK_USERS, MOCK_COMPANIES, etc.) so the
templates render immediately. Every spot that needs a real database call is marked
with "# TODO(db):". Swap those for your actual models (SQLAlchemy, Mongo, etc.)
and the routes/templates should keep working unchanged, since the shape of the
dicts passed to render_template matches what network.html / companies.html /
company_profile.html / person_profile.html expect.

Assumes you already have a way to get the logged-in user, e.g. flask_login's
current_user, or a `get_current_user()` helper — replace CURRENT_USER_ID below
with that.
"""

from flask import Blueprint, render_template, jsonify, request, abort

network_bp = Blueprint("network", __name__)

# ----------------------------------------------------------------------------
# TODO(db): replace with your auth/session mechanism
# ----------------------------------------------------------------------------
CURRENT_USER_ID = 1


# ----------------------------------------------------------------------------
# MOCK DATA — replace all of this with real queries
# ----------------------------------------------------------------------------
MOCK_USERS = {
    1: {"id": 1, "name": "You", "target_role": "Software Engineer", "role": "Software Engineer",
        "company": "CareerOS", "location": "Pune, India", "avatar_url": None,
        "bio": "Building CareerOS.", "linkedin": None,
        "skills": [{"name": "Python", "level": "Advanced", "pct": 85}],
        "education": [], "experience": []},
    2: {"id": 2, "name": "Aditi Rao", "target_role": "Data Analyst", "role": "Data Analyst",
        "company": "Fractal Analytics", "location": "Bengaluru, India", "avatar_url": None,
        "bio": "Data analyst who loves turning messy spreadsheets into decisions.",
        "linkedin": "https://linkedin.com/in/aditirao",
        "skills": [{"name": "SQL", "level": "Advanced", "pct": 90},
                   {"name": "Tableau", "level": "Intermediate", "pct": 65}],
        "education": [{"school": "BITS Pilani", "degree": "B.E. Computer Science", "years": "2019 – 2023"}],
        "experience": [{"title": "Data Analyst", "company": "Fractal Analytics", "dates": "2023 – Present"}]},
    3: {"id": 3, "name": "Rohan Mehta", "target_role": "Product Manager", "role": "Product Manager",
        "company": "Razorpay", "location": "Mumbai, India", "avatar_url": None,
        "bio": "PM focused on fintech onboarding flows.", "linkedin": None,
        "skills": [{"name": "Roadmapping", "level": "Advanced", "pct": 80}],
        "education": [], "experience": [{"title": "Associate PM", "company": "Razorpay", "dates": "2022 – Present"}]},
    4: {"id": 4, "name": "Sneha Iyer", "target_role": "UX Designer", "role": "UX Designer",
        "company": "Zoho", "location": "Chennai, India", "avatar_url": None,
        "bio": "Designing calmer B2B software.", "linkedin": None,
        "skills": [], "education": [], "experience": []},
}

# Adjacency: current user's accepted connections (set of user ids)
MOCK_CONNECTIONS = {1: {2}}

# Pending invitations: list of {id, from_id, to_id, message}
MOCK_INVITATIONS = [
    {"id": 101, "from_id": 3, "to_id": 1, "message": "Loved your roadmap post — let's connect!"},
]

MOCK_COMPANIES = {
    10: {"id": 10, "name": "Razorpay", "industry": "Fintech", "domain": "commerce_finance",
         "logo_url": None, "description": "Payments and banking infrastructure for businesses in India.",
         "website": "razorpay.com", "followers_count": 4210, "employee_count": 3,
         "employees": [MOCK_USERS[3]],
         "openings": [{"title": "Backend Engineer", "location": "Bengaluru", "type": "Full-time"}]},
    11: {"id": 11, "name": "Zoho", "industry": "Enterprise Software", "domain": "engineering_tech",
         "logo_url": None, "description": "Software suite for businesses, built and bootstrapped in India.",
         "website": "zoho.com", "followers_count": 8890, "employee_count": 1,
         "employees": [MOCK_USERS[4]], "openings": []},
    12: {"id": 12, "name": "Fractal Analytics", "industry": "AI & Analytics", "domain": "engineering_tech",
         "logo_url": None, "description": "AI and analytics consulting for enterprise clients.",
         "website": "fractal.ai", "followers_count": 2130, "employee_count": 1,
         "employees": [MOCK_USERS[2]], "openings": []},
}

# Per-user set of followed company ids
MOCK_FOLLOWS = {1: {11}}


def _connection_status(viewer_id, target_id):
    if target_id in MOCK_CONNECTIONS.get(viewer_id, set()):
        return "connected"
    for inv in MOCK_INVITATIONS:
        if inv["from_id"] == viewer_id and inv["to_id"] == target_id:
            return "pending_sent"
        if inv["from_id"] == target_id and inv["to_id"] == viewer_id:
            return "pending_received"
    return "none"


def _mutual_count(viewer_id, target_id):
    a = MOCK_CONNECTIONS.get(viewer_id, set())
    b = MOCK_CONNECTIONS.get(target_id, set())
    return len(a & b)


# ----------------------------------------------------------------------------
# PAGE ROUTES
# ----------------------------------------------------------------------------

@network_bp.route("/network")
def network():
    # TODO(db): fetch real connections/invitations/suggestions for CURRENT_USER_ID
    connected_ids = MOCK_CONNECTIONS.get(CURRENT_USER_ID, set())
    connections = [MOCK_USERS[uid] for uid in connected_ids if uid in MOCK_USERS]

    invitations = []
    for inv in MOCK_INVITATIONS:
        if inv["to_id"] == CURRENT_USER_ID:
            invitations.append({
                "id": inv["id"],
                "from_user": MOCK_USERS[inv["from_id"]],
                "message": inv.get("message"),
            })

    already_related = connected_ids | {inv["from_id"] for inv in MOCK_INVITATIONS if inv["to_id"] == CURRENT_USER_ID} \
        | {inv["to_id"] for inv in MOCK_INVITATIONS if inv["from_id"] == CURRENT_USER_ID} | {CURRENT_USER_ID}
    suggestions = []
    for uid, u in MOCK_USERS.items():
        if uid in already_related:
            continue
        s = dict(u)
        s["mutual_count"] = _mutual_count(CURRENT_USER_ID, uid)
        suggestions.append(s)

    return render_template(
        "network.html",
        connections=connections,
        invitations=invitations,
        suggestions=suggestions,
    )


@network_bp.route("/u/<int:user_id>")
def person_profile(user_id):
    # TODO(db): fetch the target user's public profile fields
    viewed_user = MOCK_USERS.get(user_id)
    if not viewed_user:
        abort(404)
    return render_template(
        "person_profile.html",
        viewed_user=viewed_user,
        connection_status=_connection_status(CURRENT_USER_ID, user_id),
        mutual_connections=_mutual_count(CURRENT_USER_ID, user_id),
    )


@network_bp.route("/companies")
def companies():
    # TODO(db): fetch company list, and is_following per company for CURRENT_USER_ID
    follows = MOCK_FOLLOWS.get(CURRENT_USER_ID, set())
    company_list = []
    for c in MOCK_COMPANIES.values():
        cc = dict(c)
        cc["is_following"] = c["id"] in follows
        company_list.append(cc)
    return render_template("companies.html", companies=company_list)


@network_bp.route("/companies/<int:company_id>")
def company_profile(company_id):
    company = MOCK_COMPANIES.get(company_id)
    if not company:
        abort(404)
    company = dict(company)
    company["is_following"] = company_id in MOCK_FOLLOWS.get(CURRENT_USER_ID, set())
    return render_template("company_profile.html", company=company)


# ----------------------------------------------------------------------------
# API — CONNECTIONS / INVITATIONS
# ----------------------------------------------------------------------------

@network_bp.route("/api/network/connect/<int:user_id>", methods=["POST"])
def api_send_invitation(user_id):
    if user_id not in MOCK_USERS:
        abort(404)
    # TODO(db): insert an invitation row (from=CURRENT_USER_ID, to=user_id)
    new_id = max((i["id"] for i in MOCK_INVITATIONS), default=100) + 1
    MOCK_INVITATIONS.append({"id": new_id, "from_id": CURRENT_USER_ID, "to_id": user_id, "message": None})
    return jsonify({"status": "pending", "invitation_id": new_id})


@network_bp.route("/api/network/connect/<int:user_id>/accept-from-profile", methods=["POST"])
def api_accept_from_profile(user_id):
    # Convenience endpoint used by person_profile.html, where we only know the
    # other user's id, not the invitation id.
    # TODO(db): find the invitation where from_id=user_id, to_id=CURRENT_USER_ID
    inv = next((i for i in MOCK_INVITATIONS if i["from_id"] == user_id and i["to_id"] == CURRENT_USER_ID), None)
    if not inv:
        abort(404)
    MOCK_INVITATIONS.remove(inv)
    MOCK_CONNECTIONS.setdefault(CURRENT_USER_ID, set()).add(user_id)
    MOCK_CONNECTIONS.setdefault(user_id, set()).add(CURRENT_USER_ID)
    return jsonify({"status": "connected"})


@network_bp.route("/api/network/invitations/<int:invite_id>/accept", methods=["POST"])
def api_accept_invitation(invite_id):
    inv = next((i for i in MOCK_INVITATIONS if i["id"] == invite_id), None)
    if not inv or inv["to_id"] != CURRENT_USER_ID:
        abort(404)
    # TODO(db): move invitation -> connections table (both directions), delete invitation row
    MOCK_INVITATIONS.remove(inv)
    MOCK_CONNECTIONS.setdefault(CURRENT_USER_ID, set()).add(inv["from_id"])
    MOCK_CONNECTIONS.setdefault(inv["from_id"], set()).add(CURRENT_USER_ID)
    return jsonify({"status": "connected"})


@network_bp.route("/api/network/invitations/<int:invite_id>/decline", methods=["POST"])
def api_decline_invitation(invite_id):
    inv = next((i for i in MOCK_INVITATIONS if i["id"] == invite_id), None)
    if not inv or inv["to_id"] != CURRENT_USER_ID:
        abort(404)
    # TODO(db): delete invitation row
    MOCK_INVITATIONS.remove(inv)
    return jsonify({"status": "declined"})


@network_bp.route("/api/network/connections/<int:user_id>", methods=["DELETE"])
def api_remove_connection(user_id):
    # TODO(db): delete the connection row(s) between CURRENT_USER_ID and user_id
    MOCK_CONNECTIONS.get(CURRENT_USER_ID, set()).discard(user_id)
    MOCK_CONNECTIONS.get(user_id, set()).discard(CURRENT_USER_ID)
    return jsonify({"status": "removed"})


# ----------------------------------------------------------------------------
# API — COMPANIES
# ----------------------------------------------------------------------------

@network_bp.route("/api/companies/<int:company_id>/follow", methods=["POST"])
def api_follow_company(company_id):
    if company_id not in MOCK_COMPANIES:
        abort(404)
    # TODO(db): insert follow row, increment companies.followers_count
    MOCK_FOLLOWS.setdefault(CURRENT_USER_ID, set()).add(company_id)
    return jsonify({"status": "following"})


@network_bp.route("/api/companies/<int:company_id>/follow", methods=["DELETE"])
def api_unfollow_company(company_id):
    if company_id not in MOCK_COMPANIES:
        abort(404)
    # TODO(db): delete follow row, decrement companies.followers_count
    MOCK_FOLLOWS.get(CURRENT_USER_ID, set()).discard(company_id)
    return jsonify({"status": "not_following"})


# ----------------------------------------------------------------------------
# API — SEARCH (people + companies)
# ----------------------------------------------------------------------------

@network_bp.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return jsonify({"people": [], "companies": []})

    # TODO(db): replace with a real full-text / ILIKE query against your users
    # and companies tables (and probably a search index once this scales)
    people = [u for u in MOCK_USERS.values() if q in u["name"].lower() and u["id"] != CURRENT_USER_ID]
    companies_ = [c for c in MOCK_COMPANIES.values() if q in c["name"].lower()]

    return jsonify({
        "people": [{"id": p["id"], "name": p["name"], "role": p.get("role")} for p in people],
        "companies": [{"id": c["id"], "name": c["name"], "industry": c["industry"]} for c in companies_],
    })
