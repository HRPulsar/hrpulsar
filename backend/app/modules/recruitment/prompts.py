"""AI prompt templates for recruitment module."""

SYSTEM_RECRUITER = (
    "You are an expert HR/recruiting AI assistant. You help create competency profiles, "
    "parse resumes, and generate individual interview questions. Always output valid JSON. "
    "Be precise, professional, and thorough. "
    "Respond in the language specified in the prompt."
)

PARSE_RESUME = """Analyze the following resume text and extract structured data.
Return a JSON object with these fields:

{{
  "first_name": "string",
  "last_name": "string",
  "middle_name": "string or null",
  "current_position": "string or null (most recent job title)",
  "years_of_experience": "integer or null (total years across all roles)",
  "location": "string or null (city or city, country)",
  "contacts": {{
    "email": "string or null",
    "phone": "string or null",
    "telegram": "string or null",
    "linkedin": "string or null",
    "location": "string or null"
  }},
  "experience": [
    {{
      "company": "string",
      "position": "string (job title)",
      "role": "string (same as position, kept for back-compat)",
      "start_date": "string or null (as written in the resume, e.g. 'Mar 2020' or '2020-03')",
      "end_date": "string or null (null or 'Present' for the current role)",
      "description": "string or null (responsibilities and achievements for this role)",
      "source_fragment": "exact quote from resume"
    }}
  ],
  "education": [
    {{
      "institution": "string",
      "degree": "string",
      "field": "string",
      "year": "integer or null"
    }}
  ],
  "skills": ["string"],
  "languages": [
    {{
      "name": "string",
      "level": "string (e.g. 'Native', 'B2', 'Fluent')"
    }}
  ],
  "certificates": [
    {{
      "title": "string",
      "issuer": "string or null",
      "year": "integer or null"
    }}
  ],
  "summary": "2-3 sentence professional summary"
}}

Important rules:
- Extract ALL information available in the resume
- Order ``experience`` newest-first; ``current_position`` mirrors
  ``experience[0].position`` when present
- Emit both ``position`` and ``role`` inside each experience entry with
  the same value (``role`` is retained for back-compat)
- ``years_of_experience`` is a best-effort integer sum of all role
  durations; use null if the resume does not state durations
- ``location`` at the top level mirrors ``contacts.location`` when
  available
- For each experience entry, include source_fragment — the exact text from the resume
- ``start_date`` / ``end_date`` keep the resume's own wording; do not
  reformat dates. ``description`` collects the role's responsibilities
  and achievements text
- Do NOT invent information not present in the resume
- If a field is not found, use null or empty array
- Do NOT extract sensitive PII (passport numbers, tax IDs, etc.)

Resume text:
{resume_text}
"""

GENERATE_PROFILE = """Generate a competency profile for the following vacancy.

Vacancy details:
- Title: {title}
- Specialization: {specialization}
- Grade: {grade}
- Description: {description}
- Tasks for 3 months: {tasks_main}
- Tasks for 1 year: {tasks_additional}
- Strategic tasks: {tasks_kpi}
- Requirements: {requirements}
- Responsibilities: {responsibilities}
- Conditions: {conditions}
{industry_context}

{attachments_section}

{clarification_section}

Generate a hierarchical competency profile as a JSON object:

{{
  "vacancy_id": "{vacancy_id}",
  "language": "{language}",
  "competences": [
    {{
      "id": "kebab-case-stable-slug-derived-from-name",
      "group": "Competence group name",
      "subgroup": "Competence subgroup name",
      "name": "Specific competence name",
      "criticality": "critical | important | desirable",
      "why_important": "Why this competence matters for this role",
      "how_manifests": "How this competence manifests in work",
      "indicators": [
        "Concrete observable behavior #1",
        "Concrete observable behavior #2",
        "Concrete observable behavior #3"
      ],
      "questions": [
        {{
          "text": "Interview question #1 (behavioral / situational)",
          "good_answer": "Example of a strong answer",
          "acceptable_answer": "Example of an acceptable answer",
          "poor_answer": "Example of a weak answer"
        }}
      ],
      "indicator_question": "Primary interview question (legacy field — mirror of questions[0].text)",
      "good_answer": "Mirror of questions[0].good_answer",
      "acceptable_answer": "Mirror of questions[0].acceptable_answer",
      "poor_answer": "Mirror of questions[0].poor_answer"
    }}
  ],
  "coverage_note": "Optional note about profile coverage"
}}

Rules:
- Generate 8-15 competences organized in 2-4 groups
- At least 50% of competences must directly relate to the tasks described
- Each competence MUST list **at least 3** distinct indicators in ``indicators``
- Each competence MUST list **at least 3** interview questions in ``questions``;
  fill ``good_answer`` / ``acceptable_answer`` / ``poor_answer`` for every one
- Keep the top-level ``indicator_question`` / ``good_answer`` / ``acceptable_answer``
  / ``poor_answer`` mirrors in sync with ``questions[0]`` — older UIs still
  read those legacy fields
- The `id` must be a stable kebab-case slug derived from the English name
  (e.g. "Senior Python skills" → "senior-python-skills"); same id = same
  competence across regenerations
- Criticality distribution: ~30% critical, ~40% important, ~30% desirable
- Questions should be behavioral (STAR format) or situational
- Good/acceptable/poor answers should be realistic and distinguishable
- Respond in {language} language
"""

GENERATE_QUESTIONS = """Generate individual interview questions for a specific candidate based on their resume and the vacancy's competency profile.

Candidate resume data:
{resume_data}

Vacancy competency profile:
{profile_data}

Vacancy title: {vacancy_title}
Language: {language}

Generate 8-15 personalized interview questions as a JSON array:

[
  {{
    "competence_name": "Name of the competence being assessed",
    "competence_group": "Group the competence belongs to",
    "question_text": "The interview question text",
    "good_answer": "Example of a strong answer for this candidate",
    "acceptable_answer": "Example of an acceptable answer",
    "poor_answer": "Example of a weak/red-flag answer",
    "resume_fragment": "Exact quote or reference from the resume this question is based on",
    "question_purpose": "clarification | depth | risk | motivation | fit",
    "priority": "must | should | nice_to_ask"
  }}
]

Rules:
- Each question MUST reference a specific fact, claim, or gap from the candidate's resume
- Each question MUST be linked to a competence from the vacancy profile
- Include resume_fragment — the exact text from the resume that prompted this question
- question_purpose categories:
  - "clarification": verify or clarify a resume claim
  - "depth": probe deeper into stated experience
  - "risk": explore potential gaps or inconsistencies
  - "motivation": understand career motivation and cultural fit
  - "fit": assess alignment with role requirements
- priority categories:
  - "must": critical questions that should not be skipped
  - "should": important but can be deprioritized if time is short
  - "nice_to_ask": supplementary questions for deeper assessment
- Distribution: ~30% must, ~40% should, ~30% nice_to_ask
- Questions should be open-ended (STAR, behavioral, situational)
- Good/acceptable/poor answers should be specific to THIS candidate's background
- Do NOT generate generic questions — every question must be personalized
- Respond in {language} language
"""
