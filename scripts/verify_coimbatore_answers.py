"""Read-only live retrieval-quality check for structured Coimbatore answers."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from app.config import Settings
from app.integrations.supabase import get_supabase_client
from app.rag.coimbatore_knowledge_provider import CoimbatoreKnowledgeProvider

CASES = (
    ("What is Pontoon Celebration?", None, None), ("How much for 8 people?", 8, "family_friends"),
    ("Is cake included?", 8, "family_friends"), ("Can pregnant guests join?", 8, "family_friends"),
    ("Where is Entartica Coimbatore?", None, None), ("Can I bring my cake?", 8, "family_friends"),
    ("Can I cancel?", 8, "family_friends"), ("Is 7pm available tomorrow?", 8, "family_friends"),
    ("How much is the photoshoot?", 8, "family_friends"), ("Do you have parking?", 8, "family_friends"),
)
def main():
    provider = CoimbatoreKnowledgeProvider(get_supabase_client(), Settings())
    for question, guests, package in CASES:
        result = provider.answer(question, guest_count=guests, package_id=package)
        print(f"query={question!r} heading={result.source_heading if result else 'none'} authority={result.authority if result else 'none'} customer_facing={result.customer_facing if result else False} live_data={result.requires_live_data if result else False}")
    return 0
if __name__ == "__main__": raise SystemExit(main())
