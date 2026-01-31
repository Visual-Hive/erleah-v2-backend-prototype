# Facet Definitions
## Multi-Faceted Vectorization Configuration

This document defines the exact facets for each entity type in the mini-assistant. These facets are the **"secret sauce"** that enables precise semantic matching.

---

## How Facets Work

### The Problem with Traditional Vector Search

```
User: "Find exhibitors selling AI monitoring tools"

Traditional search embeds the ENTIRE exhibitor profile:
"TechCorp Inc., founded in 2015, is a leading provider of enterprise 
software solutions. Based in San Francisco, we employ 500 people. 
Our CEO John Smith has 20 years experience. We offer AI monitoring 
tools, cloud infrastructure, and consulting services..."

Problem: "John Smith", "San Francisco", "2015" are rare words that 
dominate the similarity calculation. An exhibitor named "John Smith 
Consulting" might rank higher than "AI Monitor Pro" because of name 
matching, not product matching.
```

### The Solution: Semantic Facets

Instead of one big vector, we create multiple vectors, each capturing ONE semantic dimension:

```
Exhibitor: TechCorp Inc.

Facet 1 - what_we_sell:
"We sell AI monitoring and observability platforms, cloud infrastructure 
solutions, and MLOps automation tools."

Facet 2 - problems_we_solve:
"We help companies monitor AI systems in production, reduce ML 
infrastructure costs, and detect model drift early."

Facet 3 - who_we_help:
"We work with ML engineers, data science teams, DevOps engineers, 
and platform teams building AI-powered products."
...
```

When a user asks "Find exhibitors selling AI monitoring tools", we search the `what_we_sell` facet specifically, getting much better matches.

---

## Exhibitor Facets (6 Facets)

### Collection: `exhibitors_facets`

| Facet Key | Description | Template |
|-----------|-------------|----------|
| `what_we_sell` | Products, services, solutions offered | "We sell {products}. Our main offerings include {offerings}." |
| `problems_we_solve` | Pain points and challenges addressed | "We help companies {pain_points}. Our solutions address {challenges}." |
| `who_we_help` | Target customer profiles | "We work with {roles} at {company_types} who are building {projects}." |
| `our_expertise` | Technologies, industries, domains | "We are experts in {technologies}. Our team specializes in {specializations}." |
| `industries_we_serve` | Vertical markets and sectors | "We serve companies in {industries} including {examples}." |
| `why_visit_us` | Booth value proposition | "Visit our booth to {activities}. You'll learn about {topics}." |

### Exhibitor Facet Generation

```python
def generate_exhibitor_facets(exhibitor: dict) -> list[dict]:
    """Generate faceted records for an exhibitor."""
    
    base_payload = {
        "entity_id": exhibitor["id"],
        "entity_type": "exhibitor",
        "conference_id": exhibitor["conference_id"],
        "name": exhibitor["name"],
        "booth_number": exhibitor.get("booth_number", ""),
        "category": exhibitor.get("category", ""),
    }
    
    facets = []
    
    # Facet 1: What we sell
    if exhibitor.get("products") or exhibitor.get("services"):
        text = f"""What do we sell? We sell {exhibitor.get('products', 'various solutions')}.
Our main services include {exhibitor.get('services', 'consulting and support')}.
Our product categories are {exhibitor.get('category', 'technology solutions')}."""
        
        facets.append({
            "facet_key": "what_we_sell",
            "text": text,
            "payload": {**base_payload, "facet_key": "what_we_sell"},
        })
    
    # Facet 2: Problems we solve
    if exhibitor.get("value_proposition") or exhibitor.get("description"):
        text = f"""What problems do we solve? {exhibitor.get('value_proposition', '')}.
We help companies {extract_pain_points(exhibitor.get('description', ''))}.
Our solutions address challenges in {exhibitor.get('category', 'technology')}."""
        
        facets.append({
            "facet_key": "problems_we_solve",
            "text": text,
            "payload": {**base_payload, "facet_key": "problems_we_solve"},
        })
    
    # Facet 3: Who we help
    if exhibitor.get("target_audience") or exhibitor.get("ideal_customer"):
        text = f"""Who do we help? We work with {exhibitor.get('target_audience', 'technology professionals')}.
Our ideal customers are {exhibitor.get('ideal_customer', 'companies looking to innovate')}.
We're a great fit for teams working on {exhibitor.get('use_cases', 'digital transformation')}."""
        
        facets.append({
            "facet_key": "who_we_help",
            "text": text,
            "payload": {**base_payload, "facet_key": "who_we_help"},
        })
    
    # Facet 4: Our expertise
    if exhibitor.get("technologies") or exhibitor.get("specializations"):
        text = f"""What is our expertise? We are experts in {exhibitor.get('technologies', 'modern technology')}.
Our team specializes in {exhibitor.get('specializations', 'innovative solutions')}.
We have deep experience with {exhibitor.get('experience_areas', 'enterprise systems')}."""
        
        facets.append({
            "facet_key": "our_expertise",
            "text": text,
            "payload": {**base_payload, "facet_key": "our_expertise"},
        })
    
    # Facet 5: Industries we serve
    if exhibitor.get("industries") or exhibitor.get("verticals"):
        text = f"""What industries do we serve? We serve companies in {exhibitor.get('industries', 'various industries')}.
Our solutions are used in {exhibitor.get('verticals', 'multiple sectors')}.
We have customers in {exhibitor.get('customer_industries', 'technology and beyond')}."""
        
        facets.append({
            "facet_key": "industries_we_serve",
            "text": text,
            "payload": {**base_payload, "facet_key": "industries_we_serve"},
        })
    
    # Facet 6: Why visit us
    booth_text = f"""Why should you visit our booth?
Visit booth {exhibitor.get('booth_number', 'TBD')} to see {exhibitor.get('demos', 'live demonstrations')}.
You'll learn about {exhibitor.get('topics', 'our latest solutions')}.
We're offering {exhibitor.get('booth_activities', 'personalized consultations')}."""
    
    facets.append({
        "facet_key": "why_visit_us",
        "text": booth_text,
        "payload": {**base_payload, "facet_key": "why_visit_us"},
    })
    
    return facets
```

### Example: Exhibitor Facets

**Exhibitor: DataViz Pro**

```yaml
Master Record:
  name: "DataViz Pro"
  description: "DataViz Pro is a data visualization company founded in 2018. 
    We provide interactive dashboards, real-time analytics, and custom 
    reporting solutions for enterprises. Our platform supports all major 
    databases and integrates with popular BI tools."
  booth_number: "E-42"
  category: "Data & Analytics"

Faceted Records:

  what_we_sell:
    "What do we sell? We sell interactive dashboard platforms, real-time 
    analytics solutions, and custom reporting tools. Our main products 
    include DataViz Cloud, DataViz Enterprise, and DataViz Embedded."

  problems_we_solve:
    "What problems do we solve? We help companies make sense of their data.
    We solve challenges like slow reporting, siloed data, and lack of 
    real-time insights. Our platform eliminates the need for manual 
    Excel reports."

  who_we_help:
    "Who do we help? We work with data analysts, business intelligence 
    teams, and executives who need to visualize complex data. Our ideal 
    customers are companies with large datasets who want self-service 
    analytics."

  our_expertise:
    "What is our expertise? We are experts in data visualization, 
    interactive dashboards, and real-time analytics. Our team specializes 
    in D3.js, React, and high-performance data processing."

  industries_we_serve:
    "What industries do we serve? We serve companies in finance, 
    healthcare, retail, and manufacturing. Our platform is used by 
    Fortune 500 companies and fast-growing startups."

  why_visit_us:
    "Why should you visit our booth? Visit booth E-42 to see live demos 
    of our new AI-powered visualization features. We're offering free 
    30-minute consultations and exclusive conference discounts."
```

---

## Session Facets (6 Facets)

### Collection: `sessions_facets`

| Facet Key | Description | Template |
|-----------|-------------|----------|
| `session_topic` | Core subject matter | "This session covers {topic}. The main focus is {focus}." |
| `learning_outcomes` | What attendees will gain | "Attendees will learn {outcomes}. Key takeaways include {takeaways}." |
| `target_audience` | Who should attend | "This session is for {roles}. Best suited for {experience_level}." |
| `industry_focus` | Sectors and verticals covered | "This session focuses on {industries}. Examples from {sectors}." |
| `practical_applications` | Real-world use cases | "You'll see how to {applications}. Practical examples include {examples}." |
| `speaker_expertise` | Speaker background and credibility | "The speaker {speaker_name} is an expert in {expertise}." |

### Session Facet Generation

```python
def generate_session_facets(session: dict) -> list[dict]:
    """Generate faceted records for a session."""
    
    base_payload = {
        "entity_id": session["id"],
        "entity_type": "session",
        "conference_id": session["conference_id"],
        "title": session["title"],
        "start_time": session.get("start_time", ""),
        "location": session.get("location", ""),
        "speaker_name": session.get("speaker_name", ""),
    }
    
    facets = []
    
    # Facet 1: Session topic
    text = f"""What is this session about?
This session titled "{session['title']}" covers {session.get('topic', session.get('description', '')[:200])}.
The main focus is {session.get('focus', 'exploring key concepts and best practices')}.
Key themes include {session.get('themes', session.get('category', 'technology'))}."""
    
    facets.append({
        "facet_key": "session_topic",
        "text": text,
        "payload": {**base_payload, "facet_key": "session_topic"},
    })
    
    # Facet 2: Learning outcomes
    text = f"""What will I learn from this session?
Attendees will learn {session.get('learning_outcomes', 'valuable insights and techniques')}.
Key takeaways include {session.get('takeaways', 'practical knowledge you can apply immediately')}.
After this session, you'll be able to {session.get('skills_gained', 'implement what you learned')}."""
    
    facets.append({
        "facet_key": "learning_outcomes",
        "text": text,
        "payload": {**base_payload, "facet_key": "learning_outcomes"},
    })
    
    # Facet 3: Target audience
    text = f"""Who should attend this session?
This session is ideal for {session.get('target_audience', 'professionals interested in ' + session.get('category', 'this topic'))}.
Best suited for {session.get('experience_level', 'all experience levels')}.
You should attend if you're a {session.get('ideal_attendee', 'curious professional')}."""
    
    facets.append({
        "facet_key": "target_audience",
        "text": text,
        "payload": {**base_payload, "facet_key": "target_audience"},
    })
    
    # Facet 4: Industry focus
    if session.get('industries') or session.get('category'):
        text = f"""What industries does this session cover?
This session focuses on {session.get('industries', session.get('category', 'technology'))}.
Examples and case studies from {session.get('case_study_industries', 'leading companies')}.
Relevant for professionals in {session.get('relevant_industries', 'various sectors')}."""
        
        facets.append({
            "facet_key": "industry_focus",
            "text": text,
            "payload": {**base_payload, "facet_key": "industry_focus"},
        })
    
    # Facet 5: Practical applications
    text = f"""What practical skills will I gain?
You'll see how to {session.get('practical_skills', 'apply concepts in real scenarios')}.
Practical examples include {session.get('examples', 'hands-on demonstrations')}.
This session includes {session.get('format', 'interactive elements and Q&A')}."""
    
    facets.append({
        "facet_key": "practical_applications",
        "text": text,
        "payload": {**base_payload, "facet_key": "practical_applications"},
    })
    
    # Facet 6: Speaker expertise
    speaker_name = session.get('speaker_name', 'Our expert speaker')
    text = f"""Who is presenting this session?
The speaker {speaker_name} is an expert in {session.get('speaker_expertise', session.get('category', 'this field'))}.
{speaker_name} has {session.get('speaker_background', 'extensive experience in the industry')}.
You'll benefit from their insights on {session.get('speaker_insights', 'practical implementation')}."""
    
    facets.append({
        "facet_key": "speaker_expertise",
        "text": text,
        "payload": {**base_payload, "facet_key": "speaker_expertise"},
    })
    
    return facets
```

### Example: Session Facets

**Session: "Building Production ML Pipelines"**

```yaml
Master Record:
  title: "Building Production ML Pipelines"
  description: "Learn how to build reliable, scalable machine learning 
    pipelines that work in production. We'll cover MLOps best practices,
    monitoring strategies, and common pitfalls to avoid."
  speaker_name: "Dr. Sarah Chen"
  start_time: "2025-03-15T10:00:00"
  location: "Hall A"
  category: "AI & Machine Learning"

Faceted Records:

  session_topic:
    "What is this session about? This session titled 'Building Production 
    ML Pipelines' covers building reliable, scalable machine learning 
    pipelines. The main focus is MLOps best practices and production 
    deployment. Key themes include automation, monitoring, and reliability."

  learning_outcomes:
    "What will I learn from this session? Attendees will learn how to 
    design ML pipelines that scale. Key takeaways include monitoring 
    strategies, CI/CD for ML, and avoiding common production failures.
    After this session, you'll be able to deploy ML models confidently."

  target_audience:
    "Who should attend this session? This session is ideal for ML engineers, 
    data scientists moving to production, and DevOps teams supporting ML.
    Best suited for intermediate practitioners. You should attend if you've 
    built ML models but struggle to productionize them."

  industry_focus:
    "What industries does this session cover? This session focuses on 
    technology and enterprise software. Examples from fintech, e-commerce, 
    and healthcare ML deployments. Relevant for any industry using ML."

  practical_applications:
    "What practical skills will I gain? You'll see how to set up CI/CD 
    for ML, implement model monitoring, and handle data drift. Practical 
    examples include live coding and architecture diagrams."

  speaker_expertise:
    "Who is presenting this session? The speaker Dr. Sarah Chen is an 
    expert in MLOps and production machine learning. Dr. Chen has built 
    ML platforms at Google and Airbnb. You'll benefit from her insights 
    on what actually works in production."
```

---

## Speaker Facets (5 Facets)

### Collection: `speakers_facets`

| Facet Key | Description | Template |
|-----------|-------------|----------|
| `speaker_expertise` | Areas of expertise | "I am an expert in {expertise}. My specializations include {specializations}." |
| `speaker_background` | Career and experience | "I have worked at {companies}. My background includes {experience}." |
| `speaking_topics` | Topics they present on | "I speak about {topics}. My sessions cover {themes}." |
| `audience_value` | What attendees gain | "Attend my sessions to learn {value}. I help audiences {outcomes}." |
| `connect_with_me` | Networking value | "Connect with me if you're interested in {interests}. I enjoy discussing {discussion_topics}." |

### Speaker Facet Generation

```python
def generate_speaker_facets(speaker: dict) -> list[dict]:
    """Generate faceted records for a speaker."""
    
    base_payload = {
        "entity_id": speaker["id"],
        "entity_type": "speaker",
        "conference_id": speaker["conference_id"],
        "name": speaker["name"],
        "title": speaker.get("title", ""),
        "company": speaker.get("company", ""),
    }
    
    facets = []
    
    # Facet 1: Expertise
    text = f"""What is {speaker['name']}'s expertise?
{speaker['name']} is an expert in {speaker.get('expertise', speaker.get('bio', '')[:200])}.
Their specializations include {speaker.get('specializations', 'various technology areas')}.
They are known for {speaker.get('known_for', 'their thought leadership')}."""
    
    facets.append({
        "facet_key": "speaker_expertise",
        "text": text,
        "payload": {**base_payload, "facet_key": "speaker_expertise"},
    })
    
    # Facet 2: Background
    text = f"""What is {speaker['name']}'s background?
{speaker['name']} currently works as {speaker.get('title', 'a professional')} at {speaker.get('company', 'a leading company')}.
Their background includes {speaker.get('background', 'extensive industry experience')}.
Previously, they {speaker.get('previous_roles', 'held senior positions in the industry')}."""
    
    facets.append({
        "facet_key": "speaker_background",
        "text": text,
        "payload": {**base_payload, "facet_key": "speaker_background"},
    })
    
    # Facet 3: Speaking topics
    text = f"""What does {speaker['name']} speak about?
{speaker['name']} speaks about {speaker.get('topics', speaker.get('expertise', 'industry trends'))}.
Their sessions cover {speaker.get('session_themes', 'practical insights and strategies')}.
They focus on {speaker.get('focus_areas', 'helping audiences learn and grow')}."""
    
    facets.append({
        "facet_key": "speaking_topics",
        "text": text,
        "payload": {**base_payload, "facet_key": "speaking_topics"},
    })
    
    # Facet 4: Audience value
    text = f"""What will I learn from {speaker['name']}?
Attend {speaker['name']}'s sessions to learn {speaker.get('audience_value', 'practical insights')}.
{speaker['name']} helps audiences {speaker.get('helps_with', 'understand complex topics')}.
You'll gain {speaker.get('takeaways', 'actionable knowledge')}."""
    
    facets.append({
        "facet_key": "audience_value",
        "text": text,
        "payload": {**base_payload, "facet_key": "audience_value"},
    })
    
    # Facet 5: Connect
    text = f"""Why should I connect with {speaker['name']}?
Connect with {speaker['name']} if you're interested in {speaker.get('interests', speaker.get('expertise', 'technology'))}.
{speaker['name']} enjoys discussing {speaker.get('discussion_topics', 'industry trends and innovations')}.
They're open to {speaker.get('open_to', 'conversations about collaboration and learning')}."""
    
    facets.append({
        "facet_key": "connect_with_me",
        "text": text,
        "payload": {**base_payload, "facet_key": "connect_with_me"},
    })
    
    return facets
```

---

## Master Record Generation

### For All Entity Types

In addition to faceted records, we also create ONE master record per entity with the full profile. This is used for specific queries.

```python
def generate_master_record(entity: dict, entity_type: str) -> dict:
    """Generate a master record (single vector) for an entity."""
    
    if entity_type == "exhibitor":
        text = f"""{entity['name']} - {entity.get('category', 'Exhibitor')}
Booth: {entity.get('booth_number', 'TBD')}

{entity.get('description', '')}

Products & Services: {entity.get('products', '')} {entity.get('services', '')}
Target Audience: {entity.get('target_audience', '')}
Industries: {entity.get('industries', '')}"""
    
    elif entity_type == "session":
        text = f"""{entity['title']}
Speaker: {entity.get('speaker_name', 'TBA')}
Time: {entity.get('start_time', '')} | Location: {entity.get('location', '')}
Category: {entity.get('category', '')}

{entity.get('description', '')}

Learning Outcomes: {entity.get('learning_outcomes', '')}
Target Audience: {entity.get('target_audience', '')}"""
    
    elif entity_type == "speaker":
        text = f"""{entity['name']} - {entity.get('title', '')} at {entity.get('company', '')}

{entity.get('bio', '')}

Expertise: {entity.get('expertise', '')}
Speaking Topics: {entity.get('topics', '')}"""
    
    else:
        text = str(entity)
    
    return {
        "text": text,
        "payload": {
            "entity_id": entity["id"],
            "entity_type": entity_type,
            "conference_id": entity["conference_id"],
            **entity,  # Include all original fields
        }
    }
```

---

## Ingestion Scripts

### Complete Ingestion Flow

```python
# scripts/ingest_all.py
"""Ingest all entities into Qdrant with faceted and master records."""

import asyncio
from src.services.directus import get_directus_client
from src.services.qdrant import get_qdrant_service
from src.services.embedding import get_embedding_service
from qdrant_client.http.models import PointStruct
import uuid

async def ingest_conference(conference_id: str):
    """Ingest all entities for a conference."""
    
    directus = get_directus_client()
    qdrant = get_qdrant_service()
    embedding = get_embedding_service()
    
    # Ensure collections exist
    await qdrant.ensure_collections()
    
    # ==================
    # EXHIBITORS
    # ==================
    print("Ingesting exhibitors...")
    exhibitors = await directus.get_exhibitors(conference_id)
    
    # Generate master records
    master_points = []
    for exhibitor in exhibitors:
        record = generate_master_record(exhibitor, "exhibitor")
        vector = await embedding.embed_text(record["text"])
        master_points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload=record["payload"],
        ))
    
    await qdrant.upsert_points("exhibitors_master", master_points)
    print(f"  - {len(master_points)} master records")
    
    # Generate faceted records
    facet_points = []
    for exhibitor in exhibitors:
        facets = generate_exhibitor_facets(exhibitor)
        for facet in facets:
            vector = await embedding.embed_text(facet["text"])
            facet_points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload=facet["payload"],
            ))
    
    await qdrant.upsert_points("exhibitors_facets", facet_points)
    print(f"  - {len(facet_points)} faceted records")
    
    # ==================
    # SESSIONS
    # ==================
    print("Ingesting sessions...")
    sessions = await directus.get_sessions(conference_id)
    
    # Master records
    master_points = []
    for session in sessions:
        record = generate_master_record(session, "session")
        vector = await embedding.embed_text(record["text"])
        master_points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload=record["payload"],
        ))
    
    await qdrant.upsert_points("sessions_master", master_points)
    print(f"  - {len(master_points)} master records")
    
    # Faceted records
    facet_points = []
    for session in sessions:
        facets = generate_session_facets(session)
        for facet in facets:
            vector = await embedding.embed_text(facet["text"])
            facet_points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload=facet["payload"],
            ))
    
    await qdrant.upsert_points("sessions_facets", facet_points)
    print(f"  - {len(facet_points)} faceted records")
    
    # ==================
    # SPEAKERS
    # ==================
    print("Ingesting speakers...")
    speakers = await directus.get_speakers(conference_id)
    
    # Master records
    master_points = []
    for speaker in speakers:
        record = generate_master_record(speaker, "speaker")
        vector = await embedding.embed_text(record["text"])
        master_points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload=record["payload"],
        ))
    
    await qdrant.upsert_points("speakers_master", master_points)
    print(f"  - {len(master_points)} master records")
    
    # Faceted records
    facet_points = []
    for speaker in speakers:
        facets = generate_speaker_facets(speaker)
        for facet in facets:
            vector = await embedding.embed_text(facet["text"])
            facet_points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload=facet["payload"],
            ))
    
    await qdrant.upsert_points("speakers_facets", facet_points)
    print(f"  - {len(facet_points)} faceted records")
    
    print("✅ Ingestion complete!")


if __name__ == "__main__":
    import sys
    conference_id = sys.argv[1] if len(sys.argv) > 1 else "your-conference-id"
    asyncio.run(ingest_conference(conference_id))
```

---

## Facet Matching Strategy

### When to Use Faceted vs Master Search

| Query Type | Collection | Example |
|------------|------------|---------|
| **Specific** (names, keywords) | `*_master` | "Find TechCorp booth" |
| **Vague** (recommendations) | `*_facets` | "Who can help with AI?" |
| **Hybrid** (both) | Both, merge results | "AI companies in Hall A" |

### Query Classification

```python
def classify_query_type(intent: str, entities: dict) -> str:
    """Determine if query should use faceted or master search."""
    
    # Specific names → master search
    if entities.get("names"):
        return "specific"
    
    # Recommendation intents → faceted search
    if intent in ["recommendation", "general_info"]:
        return "vague"
    
    # Specific topics with filters → master search
    if entities.get("topics") and (entities.get("time") or entities.get("location")):
        return "specific"
    
    # Default to faceted for better semantic matching
    return "vague"
```

---

## Summary

| Entity | Master Collection | Facets Collection | # Facets |
|--------|-------------------|-------------------|----------|
| Exhibitors | `exhibitors_master` | `exhibitors_facets` | 6 |
| Sessions | `sessions_master` | `sessions_facets` | 6 |
| Speakers | `speakers_master` | `speakers_facets` | 5 |

**Total: 6 Qdrant collections, 17 facet types**

This multi-faceted approach is the key differentiator that makes search results dramatically more relevant compared to traditional single-vector search.
