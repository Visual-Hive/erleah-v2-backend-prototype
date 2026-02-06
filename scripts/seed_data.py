#!/usr/bin/env python3
"""
Comprehensive seed data script covering ALL business logic paths.

Coverage:
  - 4 entity types: exhibitors, sessions, speakers, attendees
  - All 25 facets from config/facets.yaml
  - Paired matching for attendees (buyer↔seller, who_i_am↔who_im_looking_for, etc.)
  - Multi-conference isolation (conf-2024, conf-2025)
  - Edge cases: non-tech domains, sparse facets, zero-result triggers
  - Directus seed: user profiles, conversations, messages
  - User profile facets for profile-based query mode testing

Usage:
    python -m scripts.seed_data                        # Seed everything
    python -m scripts.seed_data --clear                # Clear + re-seed
    python -m scripts.seed_data --qdrant-only          # Only Qdrant vectors
    python -m scripts.seed_data --directus-only        # Only Directus records
    python -m scripts.seed_data --conference conf-2024 # Specific conference only
    python -m scripts.seed_data --dry-run              # Print stats, don't ingest
"""

import asyncio
import argparse
import uuid
import sys
import os
import json

sys.path.append(os.getcwd())

from qdrant_client.http.models import PointStruct

# =============================================================================
# CONFERENCE DEFINITIONS
# =============================================================================

CONFERENCES = {
    "conf-2024": {"name": "AI & Tech Summit 2024", "year": 2024},
    "conf-2025": {"name": "Global Innovation Conference 2025", "year": 2025},
}

# =============================================================================
# EXHIBITORS — 6 facets per exhibitor (facets.yaml: exhibitors)
#
# Includes:
#   - 8 AI/tech exhibitors (original, good coverage)
#   - 2 non-tech exhibitors (edge case: different domains)
#   - 1 sparse-facet exhibitor (edge case: minimal data)
#   - 2 conf-2025 exhibitors (multi-conference isolation test)
# =============================================================================

EXHIBITORS = {
    "conf-2024": [
        # --- Core AI/Tech (8) - varied sub-domains ---
        {
            "name": "Nvidia",
            "booth": "A-01",
            "facets": {
                "what_they_sell": "AI GPUs, CUDA computing platform, deep learning accelerators, RTX graphics cards, data center solutions, edge AI devices",
                "who_they_target": "AI researchers, machine learning engineers, data scientists, game developers, autonomous vehicle companies, cloud providers",
                "their_expertise": "GPU architecture, parallel computing, deep learning frameworks, computer vision, natural language processing, robotics",
                "industries_they_serve": "Healthcare AI, autonomous vehicles, gaming, financial services, scientific research, cloud computing",
                "company_size_focus": "Enterprise companies, research institutions, startups with AI focus, government agencies",
                "geographic_focus": "Global presence, strong in North America, Europe, and Asia Pacific",
            },
        },
        {
            "name": "OpenAI",
            "booth": "A-02",
            "facets": {
                "what_they_sell": "GPT-4 API, ChatGPT Enterprise, DALL-E image generation, Whisper speech recognition, embeddings API, fine-tuning services",
                "who_they_target": "Software developers, product managers, AI startups, enterprise companies, content creators, researchers",
                "their_expertise": "Large language models, generative AI, reinforcement learning from human feedback, AI safety, multimodal AI",
                "industries_they_serve": "Technology, media and entertainment, education, healthcare, legal, customer service, marketing",
                "company_size_focus": "Startups to Fortune 500, developers and enterprises of all sizes",
                "geographic_focus": "Primarily US and Europe, expanding globally",
            },
        },
        {
            "name": "Coffee Lovers Cafe",
            "booth": "Food Court F-01",
            "facets": {
                "what_they_sell": "Premium espresso, specialty coffee, cold brew, pastries, healthy snacks, conference catering",
                "who_they_target": "Conference attendees, networking groups, early risers, afternoon break seekers",
                "their_expertise": "Barista craftsmanship, quick service, bulk orders, custom coffee blends",
                "industries_they_serve": "Events and conferences, corporate offices, hospitality",
                "company_size_focus": "Events of all sizes, from small meetups to large conferences",
                "geographic_focus": "Local presence at major tech conferences",
            },
        },
        {
            "name": "AWS",
            "booth": "A-03",
            "facets": {
                "what_they_sell": "Cloud computing infrastructure, SageMaker ML platform, Bedrock generative AI, Lambda serverless, S3 storage, EC2 compute",
                "who_they_target": "CTOs, cloud architects, DevOps engineers, data engineers, ML teams, startups",
                "their_expertise": "Cloud infrastructure, serverless computing, managed AI/ML services, scalability, security",
                "industries_they_serve": "Financial services, healthcare, retail, media, government, startups",
                "company_size_focus": "From solo developers to largest enterprises, pay-as-you-go model",
                "geographic_focus": "Global with regions in Americas, Europe, Asia Pacific, Middle East",
            },
        },
        {
            "name": "Hugging Face",
            "booth": "B-01",
            "facets": {
                "what_they_sell": "Model hub, Transformers library, Inference API, AutoTrain, Spaces hosting, enterprise solutions",
                "who_they_target": "ML engineers, NLP researchers, open source contributors, AI startups, enterprise AI teams",
                "their_expertise": "Open source ML, transformer models, NLP, computer vision, model hosting, collaborative ML",
                "industries_they_serve": "Technology, research, education, healthcare NLP, financial text analysis",
                "company_size_focus": "Open source community, startups, research labs, enterprises",
                "geographic_focus": "Global open source community, offices in US and France",
            },
        },
        {
            "name": "Anthropic",
            "booth": "A-04",
            "facets": {
                "what_they_sell": "Claude AI assistant, Claude API, enterprise solutions, constitutional AI consulting",
                "who_they_target": "Developers building AI products, enterprises needing safe AI, researchers studying AI alignment",
                "their_expertise": "AI safety, constitutional AI, large language models, interpretability research, RLHF",
                "industries_they_serve": "Technology, legal, healthcare, education, customer support, content moderation",
                "company_size_focus": "Startups to enterprises, focus on responsible AI adoption",
                "geographic_focus": "US-based with global API availability",
            },
        },
        {
            "name": "Weights & Biases",
            "booth": "B-02",
            "facets": {
                "what_they_sell": "ML experiment tracking, model versioning, dataset management, hyperparameter sweeps, collaborative dashboards",
                "who_they_target": "ML engineers, data scientists, research teams, MLOps engineers",
                "their_expertise": "Experiment tracking, model debugging, ML workflow optimization, team collaboration",
                "industries_they_serve": "AI research, autonomous vehicles, robotics, healthcare ML, any ML-heavy organization",
                "company_size_focus": "From individual researchers to large ML teams",
                "geographic_focus": "Global SaaS platform, self-hosted options available",
            },
        },
        {
            "name": "Scale AI",
            "booth": "B-03",
            "facets": {
                "what_they_sell": "Data labeling services, RLHF data collection, synthetic data generation, model evaluation",
                "who_they_target": "ML teams needing training data, autonomous vehicle companies, computer vision teams",
                "their_expertise": "High-quality data annotation, human feedback collection, data quality assurance",
                "industries_they_serve": "Autonomous vehicles, robotics, e-commerce, government, generative AI",
                "company_size_focus": "Enterprises with large data labeling needs",
                "geographic_focus": "US-based with global labeling workforce",
            },
        },
        # --- Non-tech exhibitors (edge case: different domains) ---
        {
            "name": "GreenField Agriculture Solutions",
            "booth": "C-01",
            "facets": {
                "what_they_sell": "Precision agriculture drones, soil monitoring IoT sensors, crop yield prediction software, irrigation automation systems",
                "who_they_target": "Farm owners, agricultural cooperatives, government agricultural departments, agri-tech researchers",
                "their_expertise": "Precision farming, satellite imagery analysis, drone-based crop monitoring, agricultural data analytics",
                "industries_they_serve": "Agriculture, food production, environmental monitoring, sustainable farming",
                "company_size_focus": "Small family farms to large agricultural enterprises, cooperatives",
                "geographic_focus": "North America, Southeast Asia, Sub-Saharan Africa",
            },
        },
        {
            "name": "MedSecure Health Systems",
            "booth": "C-02",
            "facets": {
                "what_they_sell": "Hospital management platform, electronic health records, telemedicine infrastructure, patient scheduling software",
                "who_they_target": "Hospital administrators, clinic managers, healthcare IT directors, medical practice owners",
                "their_expertise": "Healthcare compliance (HIPAA), medical data interoperability, HL7 FHIR integration, clinical workflows",
                "industries_they_serve": "Hospitals, clinics, telemedicine providers, health insurance, pharmaceutical companies",
                "company_size_focus": "Small clinics to large hospital networks, health systems",
                "geographic_focus": "United States and Canada, expanding to EU markets",
            },
        },
        # --- Sparse facets exhibitor (edge case: minimal data) ---
        {
            "name": "Quick Print Services",
            "booth": "D-01",
            "facets": {
                "what_they_sell": "Conference badge printing, poster printing, business cards on-demand",
                "who_they_target": "Conference organizers and attendees needing quick prints",
                "their_expertise": "Fast turnaround printing",
                "industries_they_serve": "Events",  # Short — under MIN_FACET_VALUE_LENGTH for some logic
                "company_size_focus": "",  # Empty — tests empty facet handling
                "geographic_focus": "",  # Empty
            },
        },
    ],
    "conf-2025": [
        {
            "name": "Quantum Computing Labs",
            "booth": "A-01",
            "facets": {
                "what_they_sell": "Quantum processors, quantum cloud computing access, quantum algorithm consulting, Qiskit development tools",
                "who_they_target": "Quantum researchers, cryptography experts, pharmaceutical companies, financial quants",
                "their_expertise": "Superconducting qubits, quantum error correction, quantum machine learning, post-quantum cryptography",
                "industries_they_serve": "Pharmaceuticals, cryptography, financial modeling, materials science, logistics optimization",
                "company_size_focus": "Research institutions, Fortune 500 companies, government labs",
                "geographic_focus": "US, Europe, Japan, with quantum cloud accessible globally",
            },
        },
        {
            "name": "RoboTech Industrial",
            "booth": "A-02",
            "facets": {
                "what_they_sell": "Industrial robotic arms, warehouse automation systems, collaborative robots (cobots), robot fleet management software",
                "who_they_target": "Manufacturing plant managers, warehouse operations directors, logistics companies, automotive assembly lines",
                "their_expertise": "Industrial automation, robot vision systems, human-robot collaboration, predictive maintenance for robots",
                "industries_they_serve": "Manufacturing, warehousing, logistics, automotive, food processing",
                "company_size_focus": "Mid-size to large manufacturing and logistics companies",
                "geographic_focus": "Global, with strong presence in Germany, Japan, and United States",
            },
        },
    ],
}

# =============================================================================
# SESSIONS — 6 facets per session (facets.yaml: sessions)
#
# Includes:
#   - 8 AI/tech sessions (diverse topics, difficulty levels)
#   - 2 non-tech sessions (agriculture, healthcare business)
#   - 1 session with conflicting/niche topic (zero-result trigger)
#   - 2 conf-2025 sessions
# =============================================================================

SESSIONS = {
    "conf-2024": [
        {
            "title": "Future of AI in Healthcare",
            "speaker": "Dr. Sarah Smith",
            "location": "Main Hall",
            "time": "10:00 AM",
            "facets": {
                "session_topic": "AI diagnostics, medical imaging analysis, drug discovery, patient care optimization, clinical decision support",
                "target_audience": "Healthcare professionals, medical AI researchers, hospital IT directors, healthtech startup founders",
                "learning_outcomes": "Understand FDA approval for AI devices, implement responsible medical AI, navigate healthcare data privacy",
                "industry_focus": "Healthcare, pharmaceuticals, medical devices, health insurance, telemedicine",
                "difficulty_level": "Intermediate to advanced, assumes basic ML knowledge",
                "session_format": "Keynote presentation with live demos and Q&A",
            },
        },
        {
            "title": "Python for Data Science Workshop",
            "speaker": "Guido van Rossum",
            "location": "Room B",
            "time": "02:00 PM",
            "facets": {
                "session_topic": "Pandas data manipulation, NumPy arrays, Scikit-learn basics, data visualization with matplotlib, Jupyter notebooks",
                "target_audience": "Beginning data scientists, Python developers moving to ML, analysts learning programming",
                "learning_outcomes": "Build end-to-end data pipelines, create ML models, visualize results, handle real datasets",
                "industry_focus": "Any industry using data analysis, technology, finance, marketing analytics",
                "difficulty_level": "Beginner friendly, no prior ML experience needed",
                "session_format": "Hands-on workshop with coding exercises, bring your laptop",
            },
        },
        {
            "title": "Marketing in the Metaverse",
            "speaker": "Mark Zucker",
            "location": "Room C",
            "time": "11:00 AM",
            "facets": {
                "session_topic": "Virtual world branding, immersive advertising, avatar marketing, virtual events, NFT campaigns",
                "target_audience": "Marketing directors, brand managers, digital marketing specialists, innovation teams",
                "learning_outcomes": "Create metaverse marketing strategy, measure virtual engagement, build immersive brand experiences",
                "industry_focus": "Retail, fashion, entertainment, gaming, luxury brands",
                "difficulty_level": "Intermediate, assumes familiarity with digital marketing",
                "session_format": "Presentation with case studies and VR demo stations",
            },
        },
        {
            "title": "Building Production LLM Applications",
            "speaker": "Harrison Chase",
            "location": "Main Hall",
            "time": "02:00 PM",
            "facets": {
                "session_topic": "LangChain framework, RAG architectures, prompt engineering, agent systems, LLM deployment patterns",
                "target_audience": "Backend developers, ML engineers, technical architects building AI products",
                "learning_outcomes": "Design robust LLM pipelines, implement RAG systems, handle hallucinations, optimize costs",
                "industry_focus": "Software development, SaaS, enterprise AI, developer tools",
                "difficulty_level": "Advanced, requires Python experience and LLM familiarity",
                "session_format": "Technical deep-dive with live coding and architecture diagrams",
            },
        },
        {
            "title": "AI Safety and Alignment",
            "speaker": "Dr. Amanda Chen",
            "location": "Room A",
            "time": "04:00 PM",
            "facets": {
                "session_topic": "AI alignment research, constitutional AI, RLHF, interpretability, AI governance, existential risk",
                "target_audience": "AI researchers, policy makers, ethics officers, ML engineers concerned with safety",
                "learning_outcomes": "Understand current alignment techniques, evaluate AI risks, implement safety measures",
                "industry_focus": "AI research, government policy, technology ethics, academia",
                "difficulty_level": "Intermediate, mix of technical and policy content",
                "session_format": "Panel discussion with leading AI safety researchers",
            },
        },
        {
            "title": "Startup Pitch Competition",
            "speaker": "Multiple Founders",
            "location": "Main Hall",
            "time": "05:00 PM",
            "facets": {
                "session_topic": "AI startup pitches, venture funding, product demos, market analysis, competitive positioning",
                "target_audience": "Investors, startup founders, aspiring entrepreneurs, corporate innovation scouts",
                "learning_outcomes": "Discover emerging AI startups, understand VC perspectives, network with founders",
                "industry_focus": "Venture capital, startups, corporate innovation, technology",
                "difficulty_level": "All levels, business focused rather than technical",
                "session_format": "5-minute pitches followed by investor Q&A and audience voting",
            },
        },
        {
            "title": "MLOps Best Practices",
            "speaker": "Chip Huyen",
            "location": "Room B",
            "time": "11:00 AM",
            "facets": {
                "session_topic": "Model deployment, CI/CD for ML, monitoring in production, feature stores, model versioning",
                "target_audience": "ML engineers, DevOps engineers, data platform teams, technical leads",
                "learning_outcomes": "Build reliable ML pipelines, implement model monitoring, reduce deployment friction",
                "industry_focus": "Technology companies, any organization deploying ML at scale",
                "difficulty_level": "Advanced, assumes production engineering experience",
                "session_format": "Technical workshop with real-world case studies",
            },
        },
        {
            "title": "Computer Vision for Autonomous Vehicles",
            "speaker": "Dr. Andrej Karpathy",
            "location": "Room A",
            "time": "10:00 AM",
            "facets": {
                "session_topic": "Perception systems, sensor fusion, 3D object detection, neural network architectures for driving",
                "target_audience": "Autonomous vehicle engineers, computer vision researchers, robotics engineers",
                "learning_outcomes": "Understand AV perception stack, implement detection models, handle edge cases",
                "industry_focus": "Autonomous vehicles, robotics, transportation, logistics",
                "difficulty_level": "Advanced, deep learning expertise required",
                "session_format": "Technical lecture with visualizations from real driving data",
            },
        },
        # --- Non-tech sessions (edge case: different domains) ---
        {
            "title": "Smart Agriculture: AI on the Farm",
            "speaker": "Dr. Maria Rodriguez",
            "location": "Room D",
            "time": "09:00 AM",
            "facets": {
                "session_topic": "Precision agriculture, drone-based crop monitoring, soil health prediction, yield optimization with machine learning",
                "target_audience": "Agricultural technologists, farm managers, food supply chain professionals, agri-tech investors",
                "learning_outcomes": "Deploy AI solutions for crop management, interpret satellite and drone imagery, build predictive yield models",
                "industry_focus": "Agriculture, food production, environmental science, rural development",
                "difficulty_level": "Beginner to intermediate, no deep ML knowledge required",
                "session_format": "Presentation with field case studies and live drone demo",
            },
        },
        {
            "title": "Healthcare Business Transformation",
            "speaker": "James Wilson",
            "location": "Room D",
            "time": "03:00 PM",
            "facets": {
                "session_topic": "Hospital digital transformation, patient experience platforms, healthcare billing optimization, regulatory compliance automation",
                "target_audience": "Hospital CEOs, healthcare consultants, health-tech product managers, insurance executives",
                "learning_outcomes": "Build a digital transformation roadmap, reduce operational costs by 30%, improve patient satisfaction scores",
                "industry_focus": "Healthcare administration, health insurance, medical billing, hospital management",
                "difficulty_level": "All levels, business and strategy focused",
                "session_format": "Executive panel with case studies from leading hospital systems",
            },
        },
        # --- Niche/obscure session (edge case: very specific, likely zero results for broad queries) ---
        {
            "title": "Underwater Acoustic Signal Processing with Deep Learning",
            "speaker": "Dr. Yuki Tanaka",
            "location": "Room E",
            "time": "04:00 PM",
            "facets": {
                "session_topic": "Hydrophone array signal processing, marine mammal detection via CNN, submarine sonar classification, ocean current modeling",
                "target_audience": "Naval researchers, marine biologists using AI, oceanography data scientists",
                "learning_outcomes": "Apply deep learning to underwater acoustics, build marine species classifiers, process sonar data in real-time",
                "industry_focus": "Naval defense, marine biology, oceanography, underwater telecommunications",
                "difficulty_level": "Highly advanced, requires signal processing and deep learning expertise",
                "session_format": "Research paper presentation with acoustic sample demonstrations",
            },
        },
    ],
    "conf-2025": [
        {
            "title": "Quantum Machine Learning Frontiers",
            "speaker": "Dr. Priya Patel",
            "location": "Hall A",
            "time": "10:00 AM",
            "facets": {
                "session_topic": "Quantum neural networks, variational quantum eigensolvers, quantum kernel methods, hybrid quantum-classical optimization",
                "target_audience": "Quantum computing researchers, ML engineers exploring quantum, physics PhDs transitioning to industry",
                "learning_outcomes": "Understand quantum advantage for ML tasks, implement quantum circuits with Qiskit, evaluate quantum vs classical performance",
                "industry_focus": "Quantum computing, drug discovery, financial optimization, materials science",
                "difficulty_level": "Advanced, requires linear algebra and quantum mechanics basics",
                "session_format": "Technical seminar with Jupyter notebook walkthroughs",
            },
        },
        {
            "title": "Ethics of AI in Hiring",
            "speaker": "Prof. Lisa Thompson",
            "location": "Hall B",
            "time": "02:00 PM",
            "facets": {
                "session_topic": "Algorithmic bias in recruitment, fair ML models, EU AI Act compliance, automated resume screening ethics",
                "target_audience": "HR directors, AI ethics researchers, legal compliance officers, talent acquisition leaders",
                "learning_outcomes": "Audit AI hiring tools for bias, implement fairness metrics, comply with emerging AI regulations",
                "industry_focus": "Human resources, recruitment technology, legal compliance, corporate governance",
                "difficulty_level": "Intermediate, mix of technical and policy",
                "session_format": "Interactive workshop with bias audit exercises",
            },
        },
    ],
}

# =============================================================================
# SPEAKERS — 5 facets per speaker (facets.yaml: speakers)
#
# Includes:
#   - 6 original speakers (AI/tech)
#   - 2 additional speakers from new sessions
#   - 1 speaker with sparse/minimal bio (edge case)
#   - 2 conf-2025 speakers
# =============================================================================

SPEAKERS = {
    "conf-2024": [
        {
            "name": "Dr. Sarah Smith",
            "title": "Chief AI Officer, MedTech Corp",
            "facets": {
                "speaker_expertise": "Healthcare AI, FDA regulatory compliance, medical imaging, clinical decision support systems",
                "speaking_topics": "AI in healthcare, responsible medical AI, bridging research and clinical practice",
                "audience_value": "Learn from 15 years of healthcare AI implementation, avoid common regulatory pitfalls",
                "speaker_background": "MD/PhD Stanford, former Google Health, 50+ published papers on medical AI",
                "connect_with_me": "Healthcare AI partnerships, advisory roles, medical AI startups seeking mentorship",
            },
        },
        {
            "name": "Guido van Rossum",
            "title": "Creator of Python",
            "facets": {
                "speaker_expertise": "Python language design, programming language theory, developer productivity",
                "speaking_topics": "Python best practices, language evolution, building developer communities",
                "audience_value": "Insights from creating world's most popular language, coding philosophy",
                "speaker_background": "Python creator, former Google and Dropbox, Python BDFL emeritus",
                "connect_with_me": "Python core development, language design discussions, open source governance",
            },
        },
        {
            "name": "Harrison Chase",
            "title": "CEO, LangChain",
            "facets": {
                "speaker_expertise": "LLM application development, agent architectures, RAG systems, AI developer tools",
                "speaking_topics": "Building with LLMs, production AI systems, the future of AI development",
                "audience_value": "Practical patterns for LLM apps, lessons from thousands of LangChain users",
                "speaker_background": "Founded LangChain, former ML engineer at Robust Intelligence, Harvard CS",
                "connect_with_me": "AI developer tools partnerships, enterprise LLM implementations, startup advice",
            },
        },
        {
            "name": "Dr. Amanda Chen",
            "title": "AI Safety Researcher, Anthropic",
            "facets": {
                "speaker_expertise": "AI alignment, constitutional AI, interpretability, AI governance",
                "speaking_topics": "Making AI safe, alignment research progress, AI policy recommendations",
                "audience_value": "Understand cutting-edge safety research, implement responsible AI practices",
                "speaker_background": "PhD Berkeley AI safety, former OpenAI, published in Nature on AI risks",
                "connect_with_me": "AI safety research collaborations, policy consulting, responsible AI initiatives",
            },
        },
        {
            "name": "Chip Huyen",
            "title": "Author & MLOps Expert",
            "facets": {
                "speaker_expertise": "MLOps, ML systems design, production machine learning, real-time ML",
                "speaking_topics": "ML in production, designing ML systems, bridging research and deployment",
                "audience_value": "Practical MLOps patterns, avoid production pitfalls, scale ML teams effectively",
                "speaker_background": "Author of 'Designing ML Systems', Stanford CS instructor, NVIDIA, Snorkel AI",
                "connect_with_me": "ML platform consulting, book discussions, ML education partnerships",
            },
        },
        {
            "name": "Dr. Andrej Karpathy",
            "title": "AI Researcher & Educator",
            "facets": {
                "speaker_expertise": "Deep learning, computer vision, autonomous vehicles, neural network architectures",
                "speaking_topics": "Neural networks from scratch, Tesla Autopilot lessons, AI education",
                "audience_value": "Learn from Tesla AI leader, practical deep learning insights, career advice",
                "speaker_background": "Former Tesla AI Director, founding member OpenAI, Stanford PhD, YouTube educator",
                "connect_with_me": "AI education initiatives, autonomous vehicle research, deep learning mentorship",
            },
        },
        # --- Additional speakers for new sessions ---
        {
            "name": "Dr. Maria Rodriguez",
            "title": "Head of Agri-Tech AI, GreenField Solutions",
            "facets": {
                "speaker_expertise": "Precision agriculture, remote sensing, crop prediction models, agricultural IoT",
                "speaking_topics": "AI transforming farming, drone-based crop monitoring, sustainable agriculture technology",
                "audience_value": "Real-world agri-tech case studies, ROI from precision farming implementations",
                "speaker_background": "PhD Agricultural Engineering, MIT, 10 years leading agri-tech R&D, USDA advisor",
                "connect_with_me": "Agri-tech partnerships, sustainable farming initiatives, agricultural data sharing",
            },
        },
        {
            "name": "Dr. Yuki Tanaka",
            "title": "Marine Acoustics Researcher, JAMSTEC",
            "facets": {
                "speaker_expertise": "Underwater acoustics, deep learning for sonar, marine mammal detection, signal processing",
                "speaking_topics": "AI under the sea, applying CNNs to hydrophone data, ocean monitoring with deep learning",
                "audience_value": "Unique cross-domain AI application, novel signal processing techniques, marine conservation through AI",
                "speaker_background": "PhD Acoustics Tokyo University, 8 years at JAMSTEC, published in Journal of Ocean Engineering",
                "connect_with_me": "Marine AI collaborations, ocean data partnerships, cross-domain signal processing research",
            },
        },
        # --- Sparse speaker (edge case: very short bio) ---
        {
            "name": "James Wilson",
            "title": "Healthcare Consultant",
            "facets": {
                "speaker_expertise": "Hospital management, digital transformation",
                "speaking_topics": "Healthcare operations",
                "audience_value": "Business insights",  # Short text
                "speaker_background": "20 years in healthcare consulting",
                "connect_with_me": "",  # Empty — tests empty facet handling
            },
        },
    ],
    "conf-2025": [
        {
            "name": "Dr. Priya Patel",
            "title": "Quantum ML Researcher, IBM Quantum",
            "facets": {
                "speaker_expertise": "Quantum machine learning, variational algorithms, quantum error mitigation, Qiskit development",
                "speaking_topics": "Quantum advantage for real problems, hybrid quantum-classical systems, quantum computing roadmap",
                "audience_value": "Hands-on quantum ML experience, understand when quantum beats classical, future-proof your ML skills",
                "speaker_background": "PhD Physics Caltech, IBM Quantum Research since 2020, 30+ papers on quantum ML",
                "connect_with_me": "Quantum research collaborations, Qiskit community, quantum startup advisory",
            },
        },
        {
            "name": "Prof. Lisa Thompson",
            "title": "AI Ethics Professor, Stanford",
            "facets": {
                "speaker_expertise": "Algorithmic fairness, AI regulation, tech ethics, responsible innovation",
                "speaking_topics": "Bias in AI hiring, EU AI Act, building ethical AI organizations, fairness metrics",
                "audience_value": "Practical fairness auditing frameworks, regulatory compliance guidance, ethical AI culture building",
                "speaker_background": "Stanford Ethics in Society, former Google AI ethics team, advisor to EU Commission on AI",
                "connect_with_me": "AI policy consulting, ethics board advisory, academic-industry ethics partnerships",
            },
        },
    ],
}

# =============================================================================
# ATTENDEES — 8 facets per attendee with PAIRED matching (facets.yaml: attendees)
#
# This is the "secret sauce" — buyer↔seller paired facet matching.
# Pairs:
#   products_i_want_to_sell ↔ products_i_want_to_buy
#   who_i_am ↔ who_im_looking_for
#   my_expertise ↔ what_i_want_to_learn
#   industries_i_work_in ↔ industries_i_work_in (self-pair)
#   my_goals_at_event ↔ my_goals_at_event (self-pair)
#
# Includes:
#   - 12 attendees with diverse profiles for rich paired matching
#   - Complementary pairs (buyer A matches seller B)
#   - Sparse profiles (1-2 attendees with few facets filled)
#   - Cross-domain attendees (non-tech backgrounds)
# =============================================================================

ATTENDEES = {
    "conf-2024": [
        # --- AI Startup Founder (SELLER: AI tools) ---
        {
            "name": "Alex Rivera",
            "title": "CEO, NeuralDeploy",
            "user_id": "attendee-001",
            "facets": {
                "products_i_want_to_sell": "MLOps deployment platform, one-click model serving, automated A/B testing for ML models, GPU cluster management",
                "products_i_want_to_buy": "Enterprise sales automation tools, CRM for B2B SaaS, cloud credits, marketing services for developer tools",
                "who_i_am": "AI startup founder, former Google ML engineer, Y Combinator alumni, building developer tools for MLOps",
                "who_im_looking_for": "Enterprise customers deploying ML at scale, ML platform engineering leads, venture capital investors, strategic partners",
                "my_expertise": "ML deployment pipelines, Kubernetes for ML, model monitoring, startup scaling from 0 to $1M ARR",
                "what_i_want_to_learn": "Enterprise sales strategies, go-to-market for developer tools, fundraising for Series A",
                "industries_i_work_in": "AI/ML tooling, developer tools, enterprise SaaS, cloud infrastructure",
                "my_goals_at_event": "Find enterprise pilot customers, meet Series A investors, recruit senior engineers, demo NeuralDeploy platform",
            },
        },
        # --- Enterprise Buyer (BUYER: ML infrastructure) ---
        {
            "name": "Sarah Kim",
            "title": "VP of Engineering, FinanceAI Corp",
            "user_id": "attendee-002",
            "facets": {
                "products_i_want_to_sell": "Financial risk analysis APIs, real-time fraud detection models, regulatory compliance automation",
                "products_i_want_to_buy": "MLOps platforms for production deployment, GPU computing solutions, model monitoring and observability tools, data labeling services",
                "who_i_am": "VP Engineering at a fintech company, managing 50-person ML team, responsible for ML infrastructure decisions",
                "who_im_looking_for": "MLOps tool vendors, GPU cloud providers, ML consultants, other enterprise ML leaders for best practices sharing",
                "my_expertise": "Financial ML models, real-time prediction systems, regulatory compliance, team management at scale",
                "what_i_want_to_learn": "Latest MLOps best practices, cost optimization for GPU workloads, model governance frameworks",
                "industries_i_work_in": "Financial services, fintech, insurance, banking technology",
                "my_goals_at_event": "Evaluate MLOps vendors for our platform migration, benchmark our ML practices against peers, hire ML engineers",
            },
        },
        # --- Data Scientist (LEARNER) ---
        {
            "name": "Marco Rossi",
            "title": "Senior Data Scientist, RetailMax",
            "user_id": "attendee-003",
            "facets": {
                "products_i_want_to_sell": "Demand forecasting models, customer segmentation algorithms, retail analytics dashboards",
                "products_i_want_to_buy": "LLM API access for customer chatbots, vector database for product recommendations, embedding model APIs",
                "who_i_am": "Data scientist with 5 years retail ML experience, Python expert, transitioning into LLM applications",
                "who_im_looking_for": "LLM experts who can mentor on RAG systems, other retail data scientists, potential co-founders for AI startup",
                "my_expertise": "Retail analytics, demand forecasting, customer lifetime value prediction, Python data science stack",
                "what_i_want_to_learn": "LangChain and RAG architectures, fine-tuning LLMs for domain-specific tasks, prompt engineering best practices",
                "industries_i_work_in": "Retail, e-commerce, consumer goods, marketing analytics",
                "my_goals_at_event": "Deep-dive into LLM workshops, network with LangChain community, explore startup opportunities in retail AI",
            },
        },
        # --- Healthcare AI Researcher ---
        {
            "name": "Dr. Emily Watson",
            "title": "AI Research Lead, MayoHealth AI Lab",
            "user_id": "attendee-004",
            "facets": {
                "products_i_want_to_sell": "Medical image analysis models (radiology AI), FDA-approved diagnostic algorithms, clinical trial optimization tools",
                "products_i_want_to_buy": "High-quality medical training data, HIPAA-compliant cloud computing, annotation tools for medical images",
                "who_i_am": "Healthcare AI researcher, MD with ML background, leading team of 15 at major medical center",
                "who_im_looking_for": "Medical data providers, HIPAA-compliant cloud vendors, pharma companies interested in AI diagnostics, FDA regulatory consultants",
                "my_expertise": "Medical imaging AI, FDA AI/ML device regulation, clinical validation studies, radiology workflow optimization",
                "what_i_want_to_learn": "Latest computer vision architectures, federated learning for healthcare, synthetic medical data generation",
                "industries_i_work_in": "Healthcare, medical devices, pharmaceuticals, clinical research",
                "my_goals_at_event": "Find data partners for multi-site clinical studies, learn about federated learning, present our radiology AI results",
            },
        },
        # --- Investor ---
        {
            "name": "David Chen",
            "title": "Partner, TechVentures Capital",
            "user_id": "attendee-005",
            "facets": {
                "products_i_want_to_sell": "Series A/B funding for AI startups, portfolio company introductions, venture advisory services",
                "products_i_want_to_buy": "Deal flow from AI founders, market intelligence on AI trends, co-investment opportunities with other VCs",
                "who_i_am": "Venture capital partner focused on AI/ML investments, managing $200M fund, board member of 8 AI companies",
                "who_im_looking_for": "AI startup founders seeking Series A/B, other investors for co-investment, technical advisors for portfolio companies",
                "my_expertise": "AI startup evaluation, market sizing for AI products, board governance, fundraising strategy",
                "what_i_want_to_learn": "Emerging AI application areas, technical due diligence frameworks, AI market trends 2025",
                "industries_i_work_in": "Venture capital, startup ecosystem, AI/ML technology, enterprise software",
                "my_goals_at_event": "Source 5+ investable AI startups, meet co-investors, attend pitch competition, understand emerging trends",
            },
        },
        # --- DevOps/Platform Engineer (BUYER: infrastructure) ---
        {
            "name": "Priya Sharma",
            "title": "Senior Platform Engineer, CloudScale Inc",
            "user_id": "attendee-006",
            "facets": {
                "products_i_want_to_sell": "Kubernetes consulting services, cloud architecture design, DevOps training programs",
                "products_i_want_to_buy": "ML experiment tracking tools, GPU orchestration platforms, feature store solutions, observability tools for ML",
                "who_i_am": "Platform engineer specializing in ML infrastructure, Kubernetes expert, maintaining ML platform serving 200+ models",
                "who_im_looking_for": "MLOps tool vendors, GPU cloud providers, other platform engineers running ML at scale, W&B or similar vendor reps",
                "my_expertise": "Kubernetes, Terraform, ML platform engineering, CI/CD for ML, infrastructure as code",
                "what_i_want_to_learn": "Feature store best practices, GPU scheduling optimization, model serving at scale, cost management for ML infra",
                "industries_i_work_in": "Cloud infrastructure, DevOps, platform engineering, enterprise technology",
                "my_goals_at_event": "Compare MLOps tools hands-on, attend infrastructure workshops, connect with W&B and MLflow teams",
            },
        },
        # --- Non-tech: Agriculture professional ---
        {
            "name": "Carlos Martinez",
            "title": "Head of Innovation, AgroCorp International",
            "user_id": "attendee-007",
            "facets": {
                "products_i_want_to_sell": "Large-scale agricultural datasets, satellite crop imagery, farm management consulting",
                "products_i_want_to_buy": "AI crop prediction models, drone monitoring solutions, IoT sensors for soil analysis, precision irrigation systems",
                "who_i_am": "Agricultural innovation leader, managing digital transformation for 10,000+ hectare farming operation, new to AI conferences",
                "who_im_looking_for": "Agri-tech AI companies, drone solution providers, IoT sensor manufacturers, other agriculture professionals exploring AI",
                "my_expertise": "Large-scale farming operations, supply chain management, crop planning, agricultural market analysis",
                "what_i_want_to_learn": "How to apply AI to agriculture, drone monitoring implementation, IoT sensor deployment at scale, basic ML concepts",
                "industries_i_work_in": "Agriculture, food production, agri-business, supply chain",
                "my_goals_at_event": "Find technology partners for our farm digitization project, attend beginner AI sessions, network with agri-tech vendors",
            },
        },
        # --- Academic (EXPERT → looking for industry connections) ---
        {
            "name": "Prof. Robert Zhang",
            "title": "Professor of Computer Science, MIT",
            "user_id": "attendee-008",
            "facets": {
                "products_i_want_to_sell": "Research collaborations, consulting for AI safety, PhD student placement, technology licensing",
                "products_i_want_to_buy": "Industry datasets for research, GPU compute grants, funding for research projects, industry sabbatical opportunities",
                "who_i_am": "Tenured CS professor at MIT, leading AI safety research group, published 100+ papers, training next generation of AI researchers",
                "who_im_looking_for": "Industry labs hiring PhDs, companies interested in research partnerships, AI safety teams, government policy advisors",
                "my_expertise": "AI safety and alignment, formal verification of neural networks, interpretability, theoretical ML",
                "what_i_want_to_learn": "Industry perspectives on AI safety implementation, real-world deployment challenges, how companies handle AI governance",
                "industries_i_work_in": "Academia, AI research, education, technology policy",
                "my_goals_at_event": "Place PhD students in industry positions, establish research partnerships, attend AI safety panel, meet Anthropic researchers",
            },
        },
        # --- Junior Developer (LEARNER, sparse profile) ---
        {
            "name": "Lisa Park",
            "title": "Junior ML Engineer",
            "user_id": "attendee-009",
            "facets": {
                "products_i_want_to_sell": "",  # Empty — junior, nothing to sell yet
                "products_i_want_to_buy": "Online ML courses, GPU cloud credits for personal projects, coding bootcamp referrals",
                "who_i_am": "Junior ML engineer, 1 year experience, bootcamp graduate, first tech conference",
                "who_im_looking_for": "Mentors in ML engineering, hiring managers at AI companies, other junior engineers to study with",
                "my_expertise": "Python basics, scikit-learn, basic PyTorch",  # Short
                "what_i_want_to_learn": "Deep learning fundamentals, how to build real ML products, career advice for ML engineers, portfolio building",
                "industries_i_work_in": "Technology",  # Very short — under MIN_FACET_VALUE_LENGTH
                "my_goals_at_event": "Find a mentor, attend beginner workshops, get career advice, explore job opportunities at AI companies",
            },
        },
        # --- Sales/Business Development (SELLER: enterprise) ---
        {
            "name": "Michael Thompson",
            "title": "Head of Sales, DataRobot",
            "user_id": "attendee-010",
            "facets": {
                "products_i_want_to_sell": "AutoML platform, enterprise AI deployment suite, AI governance tools, data preparation automation, model management",
                "products_i_want_to_buy": "Lead generation tools, sales intelligence platforms, CRM integrations, event marketing services",
                "who_i_am": "Enterprise sales leader with 12 years in B2B SaaS, selling AI/ML platforms to Fortune 500, quota of $15M/year",
                "who_im_looking_for": "CTOs and VP Engineering at enterprises adopting AI, data science team leads, procurement decision makers, channel partners",
                "my_expertise": "Enterprise software sales, B2B SaaS go-to-market, AI platform positioning, competitive analysis, customer success",
                "what_i_want_to_learn": "What CTO priorities are for 2025, competitive landscape changes, new use cases driving AI adoption",
                "industries_i_work_in": "Enterprise software, AI/ML platforms, B2B SaaS, sales technology",
                "my_goals_at_event": "Generate 20+ qualified leads, host executive dinner, demo DataRobot to prospects, gather competitive intelligence",
            },
        },
        # --- Freelance Consultant (balanced buyer/seller) ---
        {
            "name": "Anna Kowalski",
            "title": "Independent AI Consultant",
            "user_id": "attendee-011",
            "facets": {
                "products_i_want_to_sell": "AI strategy consulting, ML project scoping, technical due diligence for AI investments, fractional CTO services",
                "products_i_want_to_buy": "Client referrals, partnership opportunities with larger consulting firms, co-working space memberships, professional development courses",
                "who_i_am": "Independent AI consultant, former McKinsey data science practice, helping mid-market companies adopt AI responsibly",
                "who_im_looking_for": "Mid-market companies starting their AI journey, VCs needing technical due diligence, other independent consultants for project collaboration",
                "my_expertise": "AI strategy, project management for ML initiatives, stakeholder communication, ROI analysis for AI investments",
                "what_i_want_to_learn": "Latest AI tools for non-technical stakeholders, consulting framework updates, emerging AI use cases for mid-market",
                "industries_i_work_in": "Management consulting, AI advisory, multiple verticals (retail, finance, manufacturing)",
                "my_goals_at_event": "Find 3-5 potential clients, expand consulting network, attend business-focused AI sessions, update knowledge on latest tools",
            },
        },
        # --- Government/Policy (non-commercial, edge case) ---
        {
            "name": "Dr. Thomas Brown",
            "title": "AI Policy Advisor, US Department of Commerce",
            "user_id": "attendee-012",
            "facets": {
                "products_i_want_to_sell": "Government AI adoption frameworks, public sector AI guidelines, international AI cooperation initiatives",
                "products_i_want_to_buy": "AI safety assessment tools, bias testing frameworks, input from industry on AI regulation impact",
                "who_i_am": "Government AI policy advisor, former tech industry executive, PhD in public policy, shaping national AI strategy",
                "who_im_looking_for": "AI company leaders for policy input, AI safety researchers, international policy counterparts, ethics board members",
                "my_expertise": "AI policy and regulation, public sector technology adoption, international tech diplomacy, government procurement",
                "what_i_want_to_learn": "Industry perspectives on AI regulation, practical AI safety measurement, how other countries approach AI governance",
                "industries_i_work_in": "Government, public policy, technology regulation, international relations",
                "my_goals_at_event": "Gather industry input for upcoming AI regulation, meet AI safety researchers, attend governance sessions, network with international delegates",
            },
        },
    ],
    "conf-2025": [
        {
            "name": "Dr. Kenji Nakamura",
            "title": "Quantum Computing Researcher, Riken",
            "user_id": "attendee-101",
            "facets": {
                "products_i_want_to_sell": "Quantum algorithm consulting, quantum error correction expertise, research collaboration opportunities",
                "products_i_want_to_buy": "Quantum cloud computing access, classical-quantum integration tools, quantum simulation hardware",
                "who_i_am": "Quantum computing researcher with 15 years experience, leading quantum ML research at RIKEN, IEEE fellow",
                "who_im_looking_for": "Industry partners for quantum applications, quantum hardware vendors, other quantum ML researchers",
                "my_expertise": "Quantum algorithms, quantum error correction, quantum machine learning, superconducting qubit systems",
                "what_i_want_to_learn": "Latest quantum hardware developments, industry use cases for quantum computing, quantum startup ecosystem",
                "industries_i_work_in": "Quantum computing, academic research, physics, high-performance computing",
                "my_goals_at_event": "Present quantum ML research, find industry collaboration partners, explore quantum startup opportunities",
            },
        },
    ],
}

# =============================================================================
# USER PROFILES — For Directus seeding and profile-based query testing
#
# These map to attendees but with the profile structure expected by:
#   - fetch_data_parallel (src/agent/nodes/fetch_data.py)
#   - update_profile (src/agent/nodes/update_profile.py)
#   - plan_queries (src/agent/nodes/plan_queries.py) — profile influences query_mode
#   - generate_acknowledgment — profile.interests used by Grok
# =============================================================================

USER_PROFILES = {
    "conf-2024": [
        {
            "user_id": "attendee-001",
            "interests": [
                "MLOps",
                "AI deployment",
                "developer tools",
                "startup scaling",
            ],
            "role": "CEO",
            "company": "NeuralDeploy",
            "looking_for": "Enterprise customers, investors, senior engineers",
            "conference_id": "conf-2024",
        },
        {
            "user_id": "attendee-002",
            "interests": ["MLOps", "GPU computing", "model monitoring", "financial AI"],
            "role": "VP of Engineering",
            "company": "FinanceAI Corp",
            "looking_for": "MLOps vendors, GPU providers, ML best practices",
            "conference_id": "conf-2024",
        },
        {
            "user_id": "attendee-003",
            "interests": ["LLMs", "RAG", "LangChain", "retail analytics"],
            "role": "Senior Data Scientist",
            "company": "RetailMax",
            "looking_for": "LLM experts, co-founders, RAG architecture guidance",
            "conference_id": "conf-2024",
        },
        {
            "user_id": "attendee-004",
            "interests": [
                "medical imaging",
                "FDA compliance",
                "computer vision",
                "federated learning",
            ],
            "role": "AI Research Lead",
            "company": "MayoHealth AI Lab",
            "looking_for": "Medical data partners, HIPAA cloud vendors, pharma companies",
            "conference_id": "conf-2024",
        },
        {
            "user_id": "attendee-005",
            "interests": ["AI investments", "startup evaluation", "market trends"],
            "role": "VC Partner",
            "company": "TechVentures Capital",
            "looking_for": "AI startups for Series A/B investment",
            "conference_id": "conf-2024",
        },
        # --- Sparse profile (minimal info, edge case for profile detection) ---
        {
            "user_id": "attendee-009",
            "interests": ["machine learning"],
            "role": "Junior ML Engineer",
            "company": "",
            "looking_for": "mentors",
            "conference_id": "conf-2024",
        },
        # --- Profile that will trigger update (user message reveals new info) ---
        {
            "user_id": "attendee-007",
            "interests": ["agriculture"],
            "role": "Head of Innovation",
            "company": "AgroCorp International",
            "looking_for": "",  # Empty — will be updated when user mentions what they want
            "conference_id": "conf-2024",
        },
    ],
    "conf-2025": [
        {
            "user_id": "attendee-101",
            "interests": ["quantum computing", "quantum ML", "error correction"],
            "role": "Researcher",
            "company": "RIKEN",
            "looking_for": "Industry quantum partners",
            "conference_id": "conf-2025",
        },
    ],
}

# =============================================================================
# CONVERSATIONS & MESSAGES — For Directus seeding
#
# Tests:
#   - get_conversation_context() — fetches recent messages
#   - Conversation history in plan_queries and generate_response
#   - Profile detection from conversation messages
# =============================================================================

CONVERSATIONS = {
    "conf-2024": [
        {
            "conversation_id": "conv-001",
            "user_id": "attendee-001",
            "conference_id": "conf-2024",
            "messages": [
                {"role": "user", "messageText": "What exhibitors have MLOps tools?"},
                {
                    "role": "assistant",
                    "messageText": "I found several exhibitors with MLOps-related offerings: Weights & Biases offers ML experiment tracking and model versioning. Scale AI provides data labeling and model evaluation. You might also want to check out AWS's SageMaker platform.",
                },
                {
                    "role": "user",
                    "messageText": "Which sessions should I attend about deploying models to production?",
                },
                {
                    "role": "assistant",
                    "messageText": "Here are the best sessions for production ML deployment: 'MLOps Best Practices' by Chip Huyen at 11 AM in Room B, and 'Building Production LLM Applications' by Harrison Chase at 2 PM in Main Hall.",
                },
            ],
        },
        {
            "conversation_id": "conv-002",
            "user_id": "attendee-003",
            "conference_id": "conf-2024",
            "messages": [
                {
                    "role": "user",
                    "messageText": "I'm interested in LangChain and RAG systems. Any relevant sessions?",
                },
                {
                    "role": "assistant",
                    "messageText": "The session 'Building Production LLM Applications' by Harrison Chase (CEO of LangChain) at 2 PM in Main Hall covers exactly what you're looking for — RAG architectures, prompt engineering, and agent systems.",
                },
            ],
        },
        # --- Empty conversation (edge case for empty history) ---
        {
            "conversation_id": "conv-003",
            "user_id": "attendee-009",
            "conference_id": "conf-2024",
            "messages": [],
        },
        # --- Profile-revealing conversation (tests profile detection) ---
        {
            "conversation_id": "conv-004",
            "user_id": "attendee-007",
            "conference_id": "conf-2024",
            "messages": [
                {
                    "role": "user",
                    "messageText": "I'm Carlos from AgroCorp. We have 10,000 hectares and I'm looking for drone monitoring solutions and AI crop prediction tools. Also interested in IoT sensors for soil analysis.",
                },
            ],
        },
        # --- Multi-turn conversation (tests history truncation to last 5) ---
        {
            "conversation_id": "conv-005",
            "user_id": "attendee-002",
            "conference_id": "conf-2024",
            "messages": [
                {"role": "user", "messageText": "What GPU options are available?"},
                {
                    "role": "assistant",
                    "messageText": "Nvidia at booth A-01 offers AI GPUs and data center solutions. AWS also provides GPU computing via their EC2 instances.",
                },
                {
                    "role": "user",
                    "messageText": "Tell me about MLOps tools specifically.",
                },
                {
                    "role": "assistant",
                    "messageText": "Weights & Biases at B-02 has experiment tracking and model versioning. The MLOps Best Practices session by Chip Huyen is highly recommended.",
                },
                {
                    "role": "user",
                    "messageText": "What about model monitoring solutions?",
                },
                {
                    "role": "assistant",
                    "messageText": "Weights & Biases includes monitoring dashboards. Scale AI offers model evaluation services. You might also want to explore DataRobot's AI governance tools.",
                },
                {"role": "user", "messageText": "Can you compare the pricing?"},
                {
                    "role": "assistant",
                    "messageText": "I don't have specific pricing information in my database. I'd recommend visiting each vendor's booth for detailed pricing discussions.",
                },
                {"role": "user", "messageText": "Who else is attending from fintech?"},
                {
                    "role": "assistant",
                    "messageText": "I can search for attendees in the fintech space. Let me look into that for you.",
                },
                {
                    "role": "user",
                    "messageText": "Actually, I also want to learn about AI safety. Any sessions on that?",
                },
            ],
        },
    ],
    "conf-2025": [
        {
            "conversation_id": "conv-101",
            "user_id": "attendee-101",
            "conference_id": "conf-2025",
            "messages": [
                {
                    "role": "user",
                    "messageText": "What quantum computing sessions are available?",
                },
            ],
        },
    ],
}

# =============================================================================
# TEST SCENARIOS — Predefined queries that exercise all code paths
# =============================================================================

TEST_SCENARIOS = [
    # --- Query Mode: specific (master search) ---
    {
        "query": "Where is the Nvidia booth?",
        "expected_mode": "specific",
        "expected_tables": ["exhibitors"],
    },
    {
        "query": "Tell me about Harrison Chase's talk",
        "expected_mode": "specific",
        "expected_tables": ["sessions", "speakers"],
    },
    # --- Query Mode: profile (faceted search with user profile) ---
    {
        "query": "What should I see today?",
        "expected_mode": "profile",
        "user_id": "attendee-003",
        "expected_tables": ["sessions", "exhibitors"],
    },
    {
        "query": "Recommend exhibitors for me",
        "expected_mode": "profile",
        "user_id": "attendee-002",
        "expected_tables": ["exhibitors"],
    },
    # --- Query Mode: hybrid ---
    {
        "query": "Sessions about deploying ML models",
        "expected_mode": "hybrid",
        "expected_tables": ["sessions"],
    },
    {
        "query": "Who sells AI hardware for startups?",
        "expected_mode": "hybrid",
        "expected_tables": ["exhibitors"],
    },
    # --- Multi-table queries ---
    {
        "query": "Tell me about AI safety — sessions, speakers, and exhibitors",
        "expected_mode": "hybrid",
        "expected_tables": ["sessions", "speakers", "exhibitors"],
    },
    # --- Attendee paired matching ---
    {
        "query": "Find people who want to buy MLOps tools",
        "expected_mode": "profile",
        "user_id": "attendee-001",
        "expected_tables": ["attendees"],
    },
    {
        "query": "Who else is in healthcare AI?",
        "expected_mode": "hybrid",
        "user_id": "attendee-004",
        "expected_tables": ["attendees"],
    },
    # --- Zero-result trigger (should trigger relax_and_retry) ---
    {
        "query": "Underwater sonar processing workshops",
        "expected_mode": "specific",
        "expected_tables": ["sessions"],
    },
    {
        "query": "Blockchain for supply chain sessions",
        "expected_mode": "hybrid",
        "expected_tables": ["sessions"],
    },
    # --- Non-tech domain ---
    {
        "query": "Agriculture AI sessions",
        "expected_mode": "hybrid",
        "expected_tables": ["sessions"],
    },
    {
        "query": "Healthcare management exhibitors",
        "expected_mode": "hybrid",
        "expected_tables": ["exhibitors"],
    },
    # --- Edge cases ---
    {
        "query": "Where can I get free coffee?",
        "expected_mode": "specific",
        "expected_tables": ["exhibitors"],
    },
    {
        "query": "Beginner friendly sessions",
        "expected_mode": "hybrid",
        "expected_tables": ["sessions"],
    },
    {
        "query": "Find mentors for junior engineers",
        "expected_mode": "profile",
        "user_id": "attendee-009",
        "expected_tables": ["attendees"],
    },
    # --- Profile update trigger ---
    {
        "query": "I'm actually a data engineer now, not just a data scientist, and I'm very interested in vector databases",
        "expected_mode": "hybrid",
        "user_id": "attendee-003",
        "triggers_profile_update": True,
    },
    # --- Cross-conference isolation ---
    {
        "query": "Quantum computing sessions",
        "conference_id": "conf-2025",
        "expected_mode": "hybrid",
        "expected_tables": ["sessions"],
    },
]


# =============================================================================
# INGESTION FUNCTIONS
# =============================================================================


async def clear_collections(qdrant, conference_ids: list[str] | None = None):
    """Delete points from Qdrant collections, optionally filtered by conference."""
    collections = [
        "exhibitors_master",
        "exhibitors_facets",
        "sessions_master",
        "sessions_facets",
        "speakers_master",
        "speakers_facets",
        "attendees_master",
        "attendees_facets",
    ]
    for coll in collections:
        try:
            if conference_ids:
                # Delete only points for specific conferences
                from qdrant_client.http.models import Filter, FieldCondition, MatchAny

                await qdrant.client.delete(
                    collection_name=coll,
                    points_selector=Filter(
                        must=[
                            FieldCondition(
                                key="conference_id", match=MatchAny(any=conference_ids)
                            )
                        ]
                    ),
                )
            else:
                # Delete all — recreate the collection
                from qdrant_client.http.models import VectorParams, Distance

                await qdrant.client.delete_collection(collection_name=coll)
                await qdrant.client.create_collection(
                    collection_name=coll,
                    vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
                )
            print(f"  Cleared {coll}")
        except Exception as e:
            print(f"  Warning: Could not clear {coll}: {e}")


async def ingest_entities(
    qdrant,
    embedding_service,
    entity_type: str,
    entities: list[dict],
    conference_id: str,
    name_field: str = "name",
    extra_payload_fields: dict | None = None,
):
    """Generic ingestion for any entity type with facets.

    Creates both master and facet vectors.
    """
    master_points = []
    facet_points = []
    facet_field_map = extra_payload_fields or {}

    for entity in entities:
        entity_id = str(uuid.uuid4())
        entity_name = entity.get(name_field, entity.get("title", "Unknown"))

        # Build base payload
        base_payload = {
            "entity_id": entity_id,
            "conference_id": conference_id,
            "type": entity_type.rstrip("s"),  # "exhibitors" → "exhibitor"
        }

        # Add entity-specific metadata fields
        for field in [
            "name",
            "title",
            "booth",
            "speaker",
            "location",
            "time",
            "user_id",
        ]:
            if field in entity:
                # Map field names to match existing code expectations
                payload_key = {
                    "booth": "booth_number",
                    "speaker": "speaker_name",
                    "time": "start_time",
                }.get(field, field)
                base_payload[payload_key] = entity[field]

        # Master vector: combined text from all facets
        facets = entity.get("facets", {})
        non_empty_facets = {k: v for k, v in facets.items() if v and len(v.strip()) > 0}

        master_parts = [entity_name]
        if (
            entity.get("title") and entity_type != "sessions"
        ):  # Avoid double "title" for sessions
            master_parts.append(entity.get("title", ""))
        master_parts.extend(non_empty_facets.values())
        master_text = ". ".join(master_parts)

        master_vector = await embedding_service.embed_text(master_text)
        master_points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=master_vector,
                payload={**base_payload, "description": master_text[:500]},
            )
        )

        # Facet vectors: one per non-empty facet
        for facet_key, facet_text in non_empty_facets.items():
            vector = await embedding_service.embed_text(facet_text)
            facet_points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        **base_payload,
                        "facet_key": facet_key,
                        "facet_text": facet_text,
                    },
                )
            )

        facet_count = len(non_empty_facets)
        total_facets = len(facets)
        sparse_marker = " (SPARSE)" if facet_count < total_facets else ""
        print(f"  + {entity_name} ({facet_count}/{total_facets} facets){sparse_marker}")

    # Upsert to Qdrant
    if master_points:
        await qdrant.upsert_points(f"{entity_type}_master", master_points)
    if facet_points:
        await qdrant.upsert_points(f"{entity_type}_facets", facet_points)

    return len(master_points), len(facet_points)


async def ingest_qdrant(
    qdrant, embedding_service, conference_ids: list[str] | None = None
):
    """Ingest all entity types into Qdrant."""
    target_conferences = conference_ids or list(CONFERENCES.keys())
    total_master = 0
    total_facets = 0

    for conf_id in target_conferences:
        print(f"\n{'=' * 60}")
        print(f"  Conference: {CONFERENCES[conf_id]['name']} ({conf_id})")
        print(f"{'=' * 60}")

        # Exhibitors
        exhibitors = EXHIBITORS.get(conf_id, [])
        if exhibitors:
            print(f"\n  Exhibitors ({len(exhibitors)}):")
            m, f = await ingest_entities(
                qdrant, embedding_service, "exhibitors", exhibitors, conf_id
            )
            total_master += m
            total_facets += f

        # Sessions
        sessions = SESSIONS.get(conf_id, [])
        if sessions:
            print(f"\n  Sessions ({len(sessions)}):")
            m, f = await ingest_entities(
                qdrant,
                embedding_service,
                "sessions",
                sessions,
                conf_id,
                name_field="title",
            )
            total_master += m
            total_facets += f

        # Speakers
        speakers = SPEAKERS.get(conf_id, [])
        if speakers:
            print(f"\n  Speakers ({len(speakers)}):")
            m, f = await ingest_entities(
                qdrant, embedding_service, "speakers", speakers, conf_id
            )
            total_master += m
            total_facets += f

        # Attendees
        attendees = ATTENDEES.get(conf_id, [])
        if attendees:
            print(f"\n  Attendees ({len(attendees)}):")
            m, f = await ingest_entities(
                qdrant, embedding_service, "attendees", attendees, conf_id
            )
            total_master += m
            total_facets += f

    return total_master, total_facets


async def seed_directus(conference_ids: list[str] | None = None):
    """Seed user profiles, conversations, and messages into Directus.

    Note: Requires a running Directus instance. Gracefully skips if unavailable.
    """
    try:
        from src.services.directus import get_directus_client

        client = get_directus_client()
    except Exception as e:
        print(f"\n  Warning: Could not connect to Directus: {e}")
        print(
            "  Skipping Directus seeding. Start Directus and retry with --directus-only"
        )
        return

    target_conferences = conference_ids or list(CONFERENCES.keys())

    # Seed user profiles
    print("\n  User Profiles:")
    for conf_id in target_conferences:
        profiles = USER_PROFILES.get(conf_id, [])
        for profile in profiles:
            try:
                user_id = profile["user_id"]
                profile_data = {k: v for k, v in profile.items() if k != "user_id"}
                await client.update_user_profile(user_id, profile_data)
                print(
                    f"    + {user_id}: {profile.get('role', 'Unknown')} at {profile.get('company', 'N/A')}"
                )
            except Exception as e:
                # Try creating instead of updating
                try:
                    resp = await client._client.post(
                        "/items/user_profiles",
                        json={
                            "id": profile["user_id"],
                            **{k: v for k, v in profile.items() if k != "user_id"},
                        },
                    )
                    print(f"    + {profile['user_id']}: Created (new)")
                except Exception as e2:
                    print(f"    ! {profile['user_id']}: Failed ({e2})")

    # Seed conversations and messages
    print("\n  Conversations & Messages:")
    for conf_id in target_conferences:
        conversations = CONVERSATIONS.get(conf_id, [])
        for conv in conversations:
            conv_id = conv["conversation_id"]
            try:
                # Create conversation
                await client._client.post(
                    "/items/conversations",
                    json={
                        "id": conv_id,
                        "user_created": conv["user_id"],
                        "conference_id": conv["conference_id"],
                        "source": "seed_data",
                        "status": "active",
                    },
                )

                # Create messages
                for msg in conv.get("messages", []):
                    await client._client.post(
                        "/items/messages",
                        json={
                            "conversation_id": conv_id,
                            "role": msg["role"],
                            "messageText": msg["messageText"],
                            "status": "completed",
                            "user_created": conv["user_id"]
                            if msg["role"] == "user"
                            else "assistant",
                        },
                    )

                msg_count = len(conv.get("messages", []))
                print(
                    f"    + {conv_id}: {msg_count} messages (user: {conv['user_id']})"
                )
            except Exception as e:
                print(f"    ! {conv_id}: Failed ({e})")


def print_stats(conference_ids: list[str] | None = None):
    """Print seed data statistics without actually ingesting."""
    target = conference_ids or list(CONFERENCES.keys())

    print("\n" + "=" * 60)
    print("  SEED DATA STATISTICS")
    print("=" * 60)

    grand_total_entities = 0
    grand_total_facets = 0
    grand_total_master = 0

    for conf_id in target:
        print(f"\n  Conference: {CONFERENCES[conf_id]['name']} ({conf_id})")
        print(f"  {'─' * 50}")

        for entity_type, data_source, facet_count in [
            ("Exhibitors", EXHIBITORS, 6),
            ("Sessions", SESSIONS, 6),
            ("Speakers", SPEAKERS, 5),
            ("Attendees", ATTENDEES, 8),
        ]:
            entities = data_source.get(conf_id, [])
            count = len(entities)
            if count:
                # Count actual non-empty facets
                total_facets = 0
                sparse_count = 0
                for e in entities:
                    facets = e.get("facets", {})
                    non_empty = sum(
                        1 for v in facets.values() if v and len(v.strip()) > 0
                    )
                    total_facets += non_empty
                    if non_empty < facet_count:
                        sparse_count += 1

                sparse_note = f" ({sparse_count} sparse)" if sparse_count else ""
                print(
                    f"    {entity_type}: {count} entities → {total_facets} facet vectors + {count} master vectors{sparse_note}"
                )
                grand_total_entities += count
                grand_total_facets += total_facets
                grand_total_master += count

        # Directus data
        profiles = USER_PROFILES.get(conf_id, [])
        conversations = CONVERSATIONS.get(conf_id, [])
        messages = sum(len(c.get("messages", [])) for c in conversations)
        if profiles or conversations:
            print(
                f"    Directus: {len(profiles)} profiles, {len(conversations)} conversations, {messages} messages"
            )

    print(f"\n  {'─' * 50}")
    print(
        f"  TOTAL: {grand_total_entities} entities, {grand_total_facets} facet vectors, {grand_total_master} master vectors"
    )
    print(f"  Conferences: {len(target)}")
    print(f"  Test scenarios: {len(TEST_SCENARIOS)}")

    # Coverage summary
    print(f"\n  BUSINESS LOGIC COVERAGE:")
    print(f"    [x] Exhibitors: 6 facets (what_they_sell, who_they_target, etc.)")
    print(f"    [x] Sessions: 6 facets (session_topic, target_audience, etc.)")
    print(f"    [x] Speakers: 5 facets (speaker_expertise, speaking_topics, etc.)")
    print(f"    [x] Attendees: 8 facets with PAIRED matching (buyer↔seller)")
    print(f"    [x] Master search (specific queries)")
    print(f"    [x] Faceted search (broad/profile queries)")
    print(f"    [x] Hybrid search (combined)")
    print(f"    [x] Paired matching (_paired_faceted_search)")
    print(f"    [x] Multi-conference isolation (conf-2024 + conf-2025)")
    print(f"    [x] Edge cases: sparse facets, empty facets, non-tech domains")
    print(f"    [x] Zero-result triggers (niche topics → relax_and_retry)")
    print(f"    [x] User profiles for Directus (profile detection, update)")
    print(f"    [x] Conversation history (multi-turn, empty, profile-revealing)")
    print(f"    [x] Profile-based query mode")
    print(f"    [x] {len(TEST_SCENARIOS)} predefined test scenarios")


# =============================================================================
# MAIN
# =============================================================================


async def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive seed data for Erleah v2 backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.seed_data                        # Seed everything
  python -m scripts.seed_data --clear                # Clear and re-seed
  python -m scripts.seed_data --qdrant-only          # Only Qdrant vectors
  python -m scripts.seed_data --directus-only        # Only Directus records
  python -m scripts.seed_data --conference conf-2024 # Specific conference
  python -m scripts.seed_data --dry-run              # Print stats only
        """,
    )
    parser.add_argument(
        "--clear", action="store_true", help="Clear existing data before seeding"
    )
    parser.add_argument(
        "--qdrant-only", action="store_true", help="Only seed Qdrant (skip Directus)"
    )
    parser.add_argument(
        "--directus-only", action="store_true", help="Only seed Directus (skip Qdrant)"
    )
    parser.add_argument(
        "--conference",
        type=str,
        help="Seed only a specific conference (e.g. conf-2024)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print statistics without ingesting"
    )
    parser.add_argument(
        "--export-scenarios", action="store_true", help="Export test scenarios to JSON"
    )
    args = parser.parse_args()

    conference_ids = [args.conference] if args.conference else None

    if args.dry_run:
        print_stats(conference_ids)
        return

    if args.export_scenarios:
        print(json.dumps(TEST_SCENARIOS, indent=2))
        return

    print("=" * 60)
    print("  ERLEAH v2 — COMPREHENSIVE SEED DATA")
    print("=" * 60)

    # --- Qdrant ---
    if not args.directus_only:
        from src.services.qdrant import get_qdrant_service
        from src.services.embedding import get_embedding_service

        qdrant = get_qdrant_service()
        embedding = get_embedding_service()

        print("\n  Ensuring Qdrant collections exist...")
        await qdrant.ensure_collections()

        if args.clear:
            print("\n  Clearing existing data...")
            await clear_collections(qdrant, conference_ids)

        total_master, total_facets = await ingest_qdrant(
            qdrant, embedding, conference_ids
        )

        print(
            f"\n  Qdrant Summary: {total_master} master vectors + {total_facets} facet vectors"
        )

    # --- Directus ---
    if not args.qdrant_only:
        print("\n  Seeding Directus...")
        await seed_directus(conference_ids)

    # --- Final Summary ---
    print_stats(conference_ids)

    print(f"\n  Test with:")
    print(f"    curl -X POST http://localhost:8000/api/chat/stream \\")
    print(f'      -H "Content-Type: application/json" \\')
    print(
        f'      -d \'{{"message": "Who sells AI hardware?", "user_context": {{"conference_id": "conf-2024"}}}}\''
    )
    print()


if __name__ == "__main__":
    asyncio.run(main())
