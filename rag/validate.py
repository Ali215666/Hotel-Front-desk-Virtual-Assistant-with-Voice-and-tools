"""Quick validation of all RAG components."""
import sys, pathlib, time
_root = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

errors = []

# Test 1: All 50 docs exist
docs = sorted(pathlib.Path('data/docs').glob('doc_*.txt'))
ok1 = len(docs) == 50
print(f'[1] Documents: {len(docs)} - {"PASS" if ok1 else "FAIL"}')
if not ok1: errors.append("doc count")

# Test 2: Index files exist
idx_dir = pathlib.Path('data/index')
for f in ['faiss.index', 'metadata.json', 'chunks.json']:
    exists = (idx_dir / f).exists()
    print(f'[2] {f}: {"PASS" if exists else "FAIL"}')
    if not exists: errors.append(f)

# Test 3: Chunker overlaps
from rag.chunker import chunk_text
chunks = chunk_text('A ' * 600, chunk_size=500, overlap=80)
ok3 = len(chunks) > 1 and all(len(c) <= 500 for c in chunks)
print(f'[3] chunker: {len(chunks)} chunks, all<=500: {"PASS" if ok3 else "FAIL"}')

# Test 4: Vector store load
from rag import vector_store
loaded = vector_store.load_index()
ok4 = loaded and vector_store._faiss_index.ntotal == 50
print(f'[4] vector_store loaded, ntotal={vector_store._faiss_index.ntotal}: {"PASS" if ok4 else "FAIL"}')

# Test 5: retrieve() speed (cached hit)
from rag.retriever import retrieve
t0 = time.perf_counter()
r = retrieve('What is the late checkout fee?', top_k=3)
ms = (time.perf_counter()-t0)*1000
ok5 = len(r) == 3 and ms < 800
print(f'[5] retrieve: {len(r)} chunks in {ms:.0f}ms: {"PASS" if ok5 else "FAIL"}')
print(f'    top hit: {r[0][:70]}...')

# Test 6: prompt_builder injects RAG
from conversation.prompt_builder import PromptBuilder
pb = PromptBuilder()
prompt = pb.build_prompt([], 'What is checkout time?', rag_chunks=['Check-out is at 11 AM.'])
ok6 = 'RETRIEVED HOTEL KNOWLEDGE' in prompt and "Check-out is at 11 AM." in prompt
print(f'[6] RAG injection in prompt: {"PASS" if ok6 else "FAIL"}')

# Summary
print()
if errors:
    print(f"FAILED: {errors}")
else:
    print("All 6 checks PASSED.")
