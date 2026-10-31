# ACCESS data dictionary
Schema version 2.0. One row per funding programme.

| Column | Meaning |
|---|---|
| `program_id` | Stable identifier (slug of the name + hash of the source URL). |
| `name` |  |
| `provider` |  |
| `provider_type` | Who funds it: government, university, foundation_charity, industry, intergovernmental, research_institute. |
| `host_country` | Display label of where it is held: country list, 'Any country' or 'Not stated'. |
| `host_countries` | Countries where the funded activity takes place (from the page; panel-checked claim). |
| `host_regions` | A region named on the page instead of countries (e.g. 'EU member states' -> Europe). |
| `host_scope` | named | anywhere (page says any country) | not_stated (page does not say, or the panel did not confirm the place) | unresolved (legacy 'Multiple', not yet re-read). A country search matches named countries, their region, anywhere, not_stated and unresolved. |
| `region` | Region where the programme is held (one region if every host country/region is in it, else Global): North America, Europe, Asia, Asia-Pacific, South America, Africa, Middle East, Global. |
| `official_url` |  |
| `official_source` |  |
| `language_of_page` |  |
| `opportunity_type` | One of: undergraduate_scholarship, masters_scholarship, phd_scholarship, postdoc_fellowship, research_fellowship, research_grant, travel_mobility_grant, research_internship, industry_fellowship, award_prize. |
| `career_levels` | Who it is for, from: undergraduate, masters, phd_candidate, postdoc, early_career, mid_career, senior, industry. |
| `fields` | Subject areas from the 25-field taxonomy; 'any' = open to all fields. |
| `duration_months` |  |
| `number_of_awards` |  |
| `summary` |  |
| `fully_funded` | True if tuition and living costs are both covered. |
| `stipend_amount` |  |
| `currency` |  |
| `stipend_period` |  |
| `covers_tuition` |  |
| `covers_travel` |  |
| `covers_research_costs` |  |
| `covers_insurance` |  |
| `nationality_allowed` | Only these nationalities may apply (empty = no restriction stated). |
| `nationality_excluded` | These nationalities may NOT apply. |
| `residency_required` |  |
| `degree_required` | Minimum degree held at application time. |
| `career_stage_required` |  |
| `max_years_since_phd` | Maximum years since PhD award at the deadline. |
| `max_age` |  |
| `min_ielts` |  |
| `min_toefl` |  |
| `min_gpa` |  |
| `min_publications` |  |
| `min_work_experience_years` |  |
| `gender` |  |
| `targeted_groups` |  |
| `conditional_criteria` |  |
| `application_cycle` |  |
| `next_deadline` | Next application deadline (ISO date) if stated. |
| `deadline_text` |  |
| `status` | open / upcoming / closed / unclear as of last verification. |
| `needs_supervisor_or_host` |  |
| `proposal_required` |  |
| `references_required` |  |
| `documents_required` |  |
| `application_url` |  |
| `service_bond` |  |
| `return_requirement` |  |
| `trust` | Weighted KPI score: source authenticity, funding-opportunity vote, rule support, verbatim evidence grounding, judge agreement, validation (0-1). |
| `band` | high / medium by calibrated trust cut-offs (low-trust rows are withheld from search). |
| `completeness` | Share of key fields present: rules, deadline, funding, documents, application link. |
| `rules_count` |  |
| `rules_dropped` |  |
| `judges` |  |
| `decision` | Critic panel outcome: accepted / accepted_with_warning / rejected. |
| `confidence` | Share of judge votes supporting the extracted rules and facts (0-1). |
| `annotated_by` |  |
| `last_verified` |  |
| `content_hash` | Fingerprint of the page text when verified; a change triggers re-annotation. |
| `schema_version` |  |