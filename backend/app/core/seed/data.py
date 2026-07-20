"""Static demo data for the tenant seed.

Pure literals only — no ORM imports, no logic. The step modules in this
package iterate over these blocks; ``scripts/seed_demo.py`` and
``ee/seed_saas.py`` import the headline org blocks to parameterise
secondary tenants.
"""

DEMO_PASSWORD = "demo1234"

PEOPLE = [
    # (first, last, position, division_key, email_prefix)
    ("Alice", "Chen", "VP of Engineering", "engineering", "alice.chen"),
    ("Bob", "Martinez", "Backend Lead", "backend", "bob.martinez"),
    ("Carol", "Johnson", "Senior Backend Developer", "backend", "carol.johnson"),
    ("David", "Kim", "Backend Developer", "backend", "david.kim"),
    ("Eva", "Petrova", "Backend Developer", "backend", "eva.petrova"),
    ("Frank", "Liu", "Junior Backend Developer", "backend", "frank.liu"),
    ("Grace", "Taylor", "Frontend Lead", "frontend", "grace.taylor"),
    ("Henry", "Wilson", "Senior Frontend Developer", "frontend", "henry.wilson"),
    ("Irene", "Nakamura", "Frontend Developer", "frontend", "irene.nakamura"),
    ("Jack", "Brown", "Frontend Developer", "frontend", "jack.brown"),
    ("Kate", "Davis", "Junior Frontend Developer", "frontend", "kate.davis"),
    ("Leo", "Garcia", "QA Lead", "qa", "leo.garcia"),
    ("Mia", "Anderson", "Senior QA Engineer", "qa", "mia.anderson"),
    ("Noah", "Thomas", "QA Engineer", "qa", "noah.thomas"),
    ("Olivia", "White", "QA Engineer", "qa", "olivia.white"),
    ("Paul", "Harris", "DevOps Lead", "devops", "paul.harris"),
    ("Quinn", "Clark", "DevOps Engineer", "devops", "quinn.clark"),
    ("Rachel", "Lewis", "DevOps Engineer", "devops", "rachel.lewis"),
    ("Sam", "Robinson", "VP of Product", "product", "sam.robinson"),
    ("Tina", "Walker", "Senior Product Manager", "product_mgmt", "tina.walker"),
    ("Uma", "Hall", "Product Manager", "product_mgmt", "uma.hall"),
    ("Victor", "Allen", "Product Analyst", "product_mgmt", "victor.allen"),
    ("Wendy", "Young", "Design Lead", "design", "wendy.young"),
    ("Xavier", "King", "Senior UX Designer", "design", "xavier.king"),
    ("Yuki", "Scott", "UI Designer", "design", "yuki.scott"),
    ("Zara", "Adams", "Head of HR", "hr", "zara.adams"),
    ("Aaron", "Baker", "HR Business Partner", "hr_bp", "aaron.baker"),
    ("Bella", "Carter", "HR Business Partner", "hr_bp", "bella.carter"),
    ("Charlie", "Evans", "Recruiter Lead", "recruiting", "charlie.evans"),
    ("Diana", "Foster", "Recruiter", "recruiting", "diana.foster"),
    ("Ethan", "Green", "Recruiter", "recruiting", "ethan.green"),
    ("Fiona", "Hughes", "L&D Manager", "learning", "fiona.hughes"),
    ("George", "Irving", "L&D Specialist", "learning", "george.irving"),
    ("Hannah", "James", "VP of Sales", "sales", "hannah.james"),
    ("Ian", "Kelly", "Senior Account Executive", "enterprise_sales", "ian.kelly"),
    ("Julia", "Lee", "Account Executive", "enterprise_sales", "julia.lee"),
    ("Kevin", "Moore", "Account Executive", "enterprise_sales", "kevin.moore"),
    ("Laura", "Nelson", "SDR Manager", "sdr", "laura.nelson"),
    ("Mike", "Owens", "SDR", "sdr", "mike.owens"),
    ("Nina", "Palmer", "SDR", "sdr", "nina.palmer"),
    ("Oscar", "Quinn", "Head of Marketing", "marketing", "oscar.quinn"),
    ("Penny", "Reed", "Content Marketing Manager", "content", "penny.reed"),
    ("Ryan", "Stone", "Content Writer", "content", "ryan.stone"),
    ("Sara", "Turner", "Growth Marketing Lead", "growth", "sara.turner"),
    ("Tom", "Underwood", "Performance Marketing", "growth", "tom.underwood"),
    ("Ursula", "Vega", "Marketing Designer", "growth", "ursula.vega"),
    ("Will", "Watson", "Events Manager", "growth", "will.watson"),
    ("Xena", "York", "Data Analyst", "product_mgmt", "xena.york"),
    ("Yuri", "Zhang", "Security Engineer", "devops", "yuri.zhang"),
    ("Abby", "Novak", "Technical Writer", "frontend", "abby.novak"),
]

DIVISIONS_L1 = [
    ("Engineering", "engineering"),
    ("Product", "product"),
    ("Human Resources", "hr"),
    ("Sales", "sales"),
    ("Marketing", "marketing"),
]

DIVISIONS_L2 = [
    ("Backend", "backend", "engineering"),
    ("Frontend", "frontend", "engineering"),
    ("QA", "qa", "engineering"),
    ("DevOps & Infrastructure", "devops", "engineering"),
    ("Product Management", "product_mgmt", "product"),
    ("Design", "design", "product"),
    ("HR Business Partners", "hr_bp", "hr"),
    ("Recruiting", "recruiting", "hr"),
    ("Learning & Development", "learning", "hr"),
    ("Enterprise Sales", "enterprise_sales", "sales"),
    ("SDR Team", "sdr", "sales"),
    ("Content Marketing", "content", "marketing"),
    ("Growth & Performance", "growth", "marketing"),
]

CUSTOM_GRADES = [
    ("CTO", "Chief Technology Officer", 10),
    ("VP", "Vice President level", 8),
    ("Director", "Director level", 7),
    ("Staff", "Staff/IC6 level", 5),
]

CUSTOM_SPECS = [
    ("Full-Stack Developer", 10),
    ("Engineering Manager", 11),
    ("Scrum Master", 12),
    ("Technical Writer", 13),
]

PREV_EMPLOYMENT_DATA = [
    # (employee_index, company, position, desc, start_days_ago, end_days_ago)
    (
        0,
        "Google",
        "Senior Software Engineer",
        "Infrastructure team, Kubernetes tooling",
        2200,
        1100,
    ),
    (0, "Stripe", "Staff Engineer", "Payments platform architecture", 1100, 400),
    (
        1,
        "Amazon",
        "Software Engineer II",
        "AWS Lambda team, serverless runtime",
        1800,
        900,
    ),
    (
        2,
        "Shopify",
        "Backend Developer",
        "Storefront API, Ruby on Rails → Python migration",
        1500,
        700,
    ),
    (
        3,
        "Accenture",
        "Junior Developer",
        "Enterprise integration projects",
        1200,
        600,
    ),
    (6, "Meta", "Frontend Engineer", "React Native core team", 2000, 1000),
    (
        6,
        "Vercel",
        "Senior Frontend Engineer",
        "Next.js framework development",
        1000,
        500,
    ),
    (
        7,
        "Spotify",
        "Frontend Developer",
        "Web player team, React + TypeScript",
        1400,
        700,
    ),
    (
        11,
        "TestRail",
        "QA Engineer",
        "Manual and automated testing for SaaS platform",
        1300,
        800,
    ),
    (
        16,
        "HashiCorp",
        "DevOps Engineer",
        "Terraform provider development",
        1600,
        700,
    ),
    (
        18,
        "McKinsey",
        "Senior Consultant",
        "Digital transformation advisory",
        2500,
        1200,
    ),
    (18, "Palantir", "Product Lead", "Enterprise analytics products", 1200, 500),
    (25, "Workday", "HR Analyst", "HRIS configuration and analytics", 1800, 900),
    (
        33,
        "HubSpot",
        "Account Executive",
        "Mid-market segment, $500K+ ARR quota",
        1700,
        800,
    ),
    (
        40,
        "Intercom",
        "Content Marketing Manager",
        "Blog, webinars, product launches",
        1300,
        700,
    ),
]

WORK_EXP_DATA = [
    # (employee_index, title, role, desc, start_days_ago, end_days_ago_or_none)
    (
        0,
        "Platform Migration to Kubernetes",
        "Technical Lead",
        "Led migration of 12 microservices to K8s",
        300,
        120,
    ),
    (
        0,
        "API Gateway Redesign",
        "Architect",
        "Designed new API gateway with rate limiting and auth",
        120,
        None,
    ),
    (
        1,
        "Payment Processing Module",
        "Lead Developer",
        "Implemented PCI-compliant payment flow",
        250,
        100,
    ),
    (
        1,
        "Database Sharding Project",
        "Lead Developer",
        "PostgreSQL sharding for multi-tenant isolation",
        100,
        None,
    ),
    (
        2,
        "User Authentication Service",
        "Developer",
        "Built OAuth2 + SAML SSO integration",
        200,
        90,
    ),
    (
        3,
        "Notification Engine",
        "Developer",
        "Real-time notifications via WebSocket + Redis pub/sub",
        180,
        60,
    ),
    (
        6,
        "Design System v2",
        "Technical Lead",
        "Component library migration from MUI to shadcn/ui",
        250,
        80,
    ),
    (
        6,
        "Performance Dashboard",
        "Lead Developer",
        "Core Web Vitals monitoring and optimization",
        80,
        None,
    ),
    (
        7,
        "Mobile-First Redesign",
        "Developer",
        "Responsive layouts for tablet and mobile users",
        200,
        100,
    ),
    (
        11,
        "E2E Test Framework",
        "Lead",
        "Playwright-based E2E test suite, 200+ test cases",
        300,
        150,
    ),
    (
        16,
        "CI/CD Pipeline Overhaul",
        "Lead",
        "Migrated from Jenkins to GitHub Actions, 3x faster builds",
        280,
        100,
    ),
    (
        18,
        "Product-Led Growth Initiative",
        "Product Owner",
        "Self-serve onboarding flow, 40% activation increase",
        200,
        None,
    ),
    (
        25,
        "Onboarding Process Redesign",
        "Project Lead",
        "Reduced new hire time-to-productivity by 30%",
        350,
        150,
    ),
]

EDUCATION_DATA = [
    # (employee_index, institution, degree, field, start_days_ago, end_days_ago)
    (0, "MIT", "M.S.", "Computer Science", 3500, 2800),
    (
        0,
        "UC Berkeley",
        "B.S.",
        "Electrical Engineering & Computer Science",
        5000,
        3600,
    ),
    (1, "Stanford University", "M.S.", "Computer Science", 3200, 2500),
    (2, "Carnegie Mellon University", "B.S.", "Computer Science", 3000, 2200),
    (3, "University of Toronto", "B.Eng.", "Software Engineering", 2800, 2000),
    (4, "Moscow State University", "M.S.", "Applied Mathematics", 3300, 2500),
    (6, "Georgia Tech", "B.S.", "Computer Science", 3600, 2800),
    (7, "University of Michigan", "B.S.", "Information Science", 3100, 2300),
    (8, "Tokyo University", "B.Eng.", "Information Engineering", 2900, 2100),
    (11, "Purdue University", "B.S.", "Computer Science", 2700, 1900),
    (16, "ETH Zurich", "M.S.", "Computer Science", 3400, 2600),
    (18, "Wharton School (UPenn)", "MBA", "Business Administration", 4000, 3200),
    (18, "Harvard University", "B.A.", "Economics", 5500, 4200),
    (22, "Rhode Island School of Design", "BFA", "Graphic Design", 3000, 2200),
    (25, "Cornell University", "M.S.", "Industrial & Labor Relations", 3200, 2400),
    (29, "University of Chicago", "MBA", "Marketing & Strategy", 3300, 2500),
    (33, "Duke University", "B.A.", "Economics", 3100, 2300),
    (40, "Northwestern University", "B.S.", "Journalism", 2900, 2100),
]

COURSES_DATA = [
    # (employee_index, title, provider, cert_url, completed_days_ago, expiry_days_ahead_or_none)
    (
        0,
        "AWS Solutions Architect Professional",
        "Amazon Web Services",
        "https://example.com/cert/aws-sap",
        200,
        730,
    ),
    (
        0,
        "Kubernetes Administrator (CKA)",
        "CNCF",
        "https://example.com/cert/cka",
        150,
        365,
    ),
    (
        1,
        "PostgreSQL Performance Tuning",
        "EnterpriseDB",
        "https://example.com/cert/pgperf",
        100,
        None,
    ),
    (1, "Python Concurrency Deep Dive", "Arjan Codes", None, 60, None),
    (
        2,
        "FastAPI Mastery",
        "TestDriven.io",
        "https://example.com/cert/fastapi",
        90,
        None,
    ),
    (
        3,
        "Redis University: RU301",
        "Redis Labs",
        "https://example.com/cert/redis",
        120,
        365,
    ),
    (
        4,
        "Machine Learning Specialization",
        "Coursera (Stanford)",
        "https://example.com/cert/ml-spec",
        180,
        None,
    ),
    (
        6,
        "Meta Frontend Developer Certificate",
        "Coursera (Meta)",
        "https://example.com/cert/meta-fe",
        250,
        None,
    ),
    (6, "Advanced React Patterns", "Frontend Masters", None, 80, None),
    (7, "TypeScript 5 Deep Dive", "Matt Pocock", None, 45, None),
    (
        11,
        "ISTQB Foundation Level",
        "ISTQB",
        "https://example.com/cert/istqb",
        400,
        None,
    ),
    (
        11,
        "Playwright Test Automation",
        "Test Automation University",
        "https://example.com/cert/playwright",
        60,
        None,
    ),
    (
        16,
        "Terraform Associate",
        "HashiCorp",
        "https://example.com/cert/terraform",
        300,
        365,
    ),
    (
        16,
        "Google Cloud Professional Cloud Architect",
        "Google Cloud",
        "https://example.com/cert/gcp-pca",
        200,
        730,
    ),
    (
        18,
        "Certified Scrum Product Owner (CSPO)",
        "Scrum Alliance",
        "https://example.com/cert/cspo",
        500,
        365,
    ),
    (25, "SHRM-CP", "SHRM", "https://example.com/cert/shrm-cp", 350, 1095),
    (
        25,
        "People Analytics Certificate",
        "Wharton Online",
        "https://example.com/cert/people-analytics",
        120,
        None,
    ),
    (
        29,
        "Google Ads Search Certification",
        "Google",
        "https://example.com/cert/gads",
        90,
        365,
    ),
    (
        33,
        "Salesforce Administrator",
        "Salesforce",
        "https://example.com/cert/sfdc-admin",
        200,
        None,
    ),
    (
        40,
        "HubSpot Content Marketing Certification",
        "HubSpot Academy",
        "https://example.com/cert/hubspot-cm",
        150,
        None,
    ),
]

COMPENSATION_DATA = [
    # (employee_index, type, amount_cents, currency, effective_days_ago, end_days_ago, notes)
    (0, "salary", 22000000, "USD", 400, None, "VP-level compensation"),
    (0, "bonus", 5000000, "USD", 30, 30, "Q1 2026 performance bonus"),
    (1, "salary", 18000000, "USD", 300, None, None),
    (2, "salary", 15000000, "USD", 350, None, None),
    (2, "salary", 13000000, "USD", 700, 350, "Before promotion to Senior"),
    (3, "salary", 12000000, "USD", 250, None, None),
    (4, "salary", 11500000, "USD", 200, None, None),
    (5, "salary", 8000000, "USD", 180, None, "Junior level"),
    (6, "salary", 19000000, "USD", 280, None, None),
    (6, "bonus", 4000000, "USD", 30, 30, "Q1 2026 leadership bonus"),
    (7, "salary", 16000000, "USD", 300, None, None),
    (8, "salary", 13000000, "USD", 250, None, None),
    (11, "salary", 17000000, "USD", 350, None, None),
    (16, "salary", 17500000, "USD", 320, None, None),
    (18, "salary", 20000000, "USD", 400, None, None),
    (22, "salary", 16500000, "USD", 300, None, None),
    (25, "salary", 14000000, "USD", 280, None, None),
    (29, "salary", 12500000, "USD", 200, None, None),
    (33, "salary", 11000000, "USD", 250, None, None),
    (33, "allowance", 50000, "USD", 200, None, "Home office stipend"),
    (40, "salary", 10000000, "USD", 220, None, None),
]

MANAGER_ASSIGNMENTS = {
    "engineering": (0, None),  # Alice Chen (VP of Engineering)
    "backend": (1, 2),  # Bob Martinez (Lead), Carol Johnson (deputy)
    "frontend": (6, 7),  # Grace Taylor (Lead), Henry Wilson (deputy)
    "qa": (11, 12),  # Leo Garcia (Lead), Mia Anderson (deputy)
    "devops": (16, None),  # Paul Harris (Lead)
    "product": (18, None),  # Sam Robinson (VP of Product)
    "product_mgmt": (19, None),  # Tina Walker (Sr PM)
    "design": (22, None),  # Wendy Young (Design Lead)
    "hr": (25, None),  # Zara Adams (Head of HR)
    "hr_bp": (26, None),  # Aaron Baker (HR BP)
    "recruiting": (28, None),  # Charlie Evans (Recruiter Lead)
    "learning": (31, None),  # Fiona Hughes (L&D Manager)
    "sales": (33, None),  # Hannah James (VP of Sales)
    "enterprise_sales": (34, None),  # Ian Kelly (Sr AE)
    "sdr": (37, None),  # Laura Nelson (SDR Manager)
    "marketing": (40, None),  # Oscar Quinn (Head of Marketing)
    "content": (41, None),  # Penny Reed (Content Marketing Mgr)
    "growth": (43, None),  # Sara Turner (Growth Marketing Lead)
}

SPEC_DIV_MAPPINGS = [
    # (specialization_title, division_key)
    ("Backend Developer", "backend"),
    ("Frontend Developer", "frontend"),
    ("QA Engineer", "qa"),
    ("DevOps Engineer", "devops"),
    ("Backend Developer", "devops"),  # DevOps also has backend skills
    ("Product Manager", "product_mgmt"),
    ("UX/UI Designer", "design"),
    ("HR Manager", "hr_bp"),
    ("HR Manager", "recruiting"),
    ("HR Manager", "learning"),
    ("Project Manager", "product_mgmt"),
    ("Data Analyst", "product_mgmt"),
]

CUSTOM_SPEC_DIV = [
    ("Full-Stack Developer", "backend"),
    ("Full-Stack Developer", "frontend"),
    ("Engineering Manager", "engineering"),
    ("Scrum Master", "product_mgmt"),
    ("Technical Writer", "frontend"),
]

EXAM_QUESTIONS_DATA = [
    (
        "What is the GIL in Python?",
        "single_choice",
        [
            (
                "A locking mechanism that prevents multiple threads from executing Python bytecodes simultaneously",
                True,
            ),
            ("A garbage collection algorithm", False),
            ("A type of Python decorator", False),
            ("A package manager for Python", False),
        ],
    ),
    (
        "Which SQL clause is used to filter grouped results?",
        "single_choice",
        [
            ("WHERE", False),
            ("HAVING", True),
            ("GROUP BY", False),
            ("ORDER BY", False),
        ],
    ),
    (
        "Select all valid HTTP methods for a REST API:",
        "multiple_choice",
        [
            ("GET", True),
            ("FETCH", False),
            ("PATCH", True),
            ("DELETE", True),
            ("SAVE", False),
        ],
    ),
    (
        "What is the difference between async and sync programming in Python?",
        "essay",
        [],
    ),
    (
        "Which of the following are Python data structures?",
        "multiple_choice",
        [
            ("list", True),
            ("tuple", True),
            ("array (built-in)", False),
            ("dict", True),
            ("set", True),
        ],
    ),
    (
        "What does ACID stand for in database context?",
        "single_choice",
        [
            ("Atomicity, Consistency, Isolation, Durability", True),
            ("Automated, Controlled, Integrated, Distributed", False),
            ("Asynchronous, Cached, Indexed, Durable", False),
            ("Advanced, Compiled, Interpreted, Deployed", False),
        ],
    ),
    (
        "What is the purpose of database indexing?",
        "single_choice",
        [
            ("To encrypt data", False),
            ("To speed up data retrieval operations", True),
            ("To compress data", False),
            ("To backup data", False),
        ],
    ),
    (
        "Explain the concept of RESTful API design and its core principles.",
        "essay",
        [],
    ),
]
