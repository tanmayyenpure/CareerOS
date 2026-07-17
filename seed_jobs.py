"""
Seeds Job with 13 sample jobs.

Run: python seed_jobs.py
"""
from app import app, db, Job

jobs = [
    # Google
    dict(company_name="Google", job_title="Backend Engineer II", location="Hyderabad",
         job_type="Onsite", experience="3–5 yrs", salary="₹28L – ₹36L",
         description="Build next-generation storage systems, high-throughput pipelines, and real-time distributed platforms using Java and Kafka.",
         skills_required="Java, Kafka, Kubernetes, gRPC", company_logo="G", domain="Cloud & Infra"),
    
    # Microsoft
    dict(company_name="Microsoft", job_title="Software Engineer, Azure Core", location="Bengaluru",
         job_type="Hybrid", experience="2–4 yrs", salary="₹24L – ₹32L",
         description="Develop highly resilient and scalable infrastructure layers for Azure Core Services using C# and Cloud architectural patterns.",
         skills_required="C#, .NET, Azure, SQL", company_logo="M", domain="Cloud & Infra"),

    # Amazon
    dict(company_name="Amazon", job_title="SDE-II, Payments Platform", location="Pune",
         job_type="Onsite", experience="3–6 yrs", salary="₹22L – ₹30L",
         description="Join the payments team to design low-latency transactional architectures, high-performance databases, and AWS integrations.",
         skills_required="Java, DynamoDB, AWS, System Design", company_logo="A", domain="Fintech"),

    # Netflix
    dict(company_name="Netflix", job_title="Senior Backend Engineer", location="Remote",
         job_type="Remote", experience="5+ yrs", salary="₹45L – ₹60L",
         description="Scale APIs powering streaming globally. Design and optimize service routing, caching, and resiliency layers.",
         skills_required="Java, Spring Boot, AWS, Docker", company_logo="N", domain="Cloud & Infra"),

    # Stripe
    dict(company_name="Stripe", job_title="Platform Engineer", location="Bengaluru",
         job_type="Hybrid", experience="3–5 yrs", salary="₹30L – ₹42L",
         description="Develop foundational platforms, dev tooling, and robust database layers to support massive transaction scales.",
         skills_required="Ruby, Go, Kubernetes, PostgreSQL", company_logo="S", domain="Fintech"),

    # Uber
    dict(company_name="Uber", job_title="SDE-II, Maps Platform", location="Hyderabad",
         job_type="Hybrid", experience="3–5 yrs", salary="₹26L – ₹35L",
         description="Build backend microservices for location tracking, routing algorithms, and map data APIs using Go.",
         skills_required="Go, Java, Kafka, Cassandra", company_logo="U", domain="Engineering & Technology"),

    # Zoho
    dict(company_name="Zoho", job_title="Site Reliability Engineer", location="Remote",
         job_type="Remote", experience="2–4 yrs", salary="₹12L – ₹18L",
         description="Ensure reliability and performance of SaaS applications. Write system automation and monitoring scripts in Bash.",
         skills_required="Linux, Bash, Incident Management, Python", company_logo="Z", domain="Cloud & Infra"),

    # Freshworks
    dict(company_name="Freshworks", job_title="Backend Developer", location="Chennai",
         job_type="Onsite", experience="1–3 yrs", salary="₹10L – ₹16L",
         description="Design customer support backend APIs. Write clean, tested code and integrate caching servers.",
         skills_required="Ruby on Rails, Redis, MySQL", company_logo="F", domain="Engineering & Technology"),

    # Razorpay
    dict(company_name="Razorpay", job_title="Backend Developer", location="Bengaluru",
         job_type="Onsite", experience="2–4 yrs", salary="₹18L – ₹25L",
         description="Design, develop and scale India's largest payment gateway API. Collaborate on system architecture and database design.",
         skills_required="Node.js, PostgreSQL, Redis, gRPC", company_logo="R", domain="Fintech"),

    # Atlassian
    dict(company_name="Atlassian", job_title="Cloud Infrastructure Engineer", location="Remote",
         job_type="Remote", experience="3–5 yrs", salary="₹25L – ₹35L",
         description="Work on developer infrastructure, scaling tooling pipelines, CI/CD, and multi-cloud environments.",
         skills_required="Docker, Terraform, Linux, Helm, GCP", company_logo="L", domain="Cloud & Infra"),

    # TCS
    dict(company_name="TCS", job_title="Python Developer", location="Pune",
         job_type="Hybrid", experience="1–3 yrs", salary="₹6L – ₹10L",
         description="Develop enterprise Python scripts, data processing modules, and REST APIs for insurance platform clients.",
         skills_required="Python, Django, SQL", company_logo="T", domain="Engineering & Technology"),

    # Infosys
    dict(company_name="Infosys", job_title="Full Stack Developer", location="Mysore",
         job_type="Onsite", experience="1–3 yrs", salary="₹5L – ₹8L",
         description="Maintain web apps, develop frontend layouts and backend controllers, and perform database migrations.",
         skills_required="Angular, Node.js, Express, MongoDB", company_logo="I", domain="Engineering & Technology"),

    # AI Startup
    dict(company_name="OpenAI Partner", job_title="AI Research Engineer", location="Bengaluru",
         job_type="Onsite", experience="3–5 yrs", salary="₹35L – ₹50L",
         description="Develop and scale ML inference microservices, fine-tune models, and design agent frameworks.",
         skills_required="Python, PyTorch, LLMs, Docker", company_logo="O", domain="AI / ML")
]

with app.app_context():
    deleted = Job.query.delete()
    print(f"Cleared {deleted} existing job(s) from 'jobs' table.")

    db.session.add_all([Job(**j) for j in jobs])
    db.session.commit()

    count = Job.query.count()
    print(f"Seeded {count} jobs successfully.")
