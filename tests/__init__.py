import os

# The tests run offline: keep the semantic injection layer (real embedding calls) switched off.
# Its logic is tested with fake embeddings in test_semantic_guard.py.
os.environ["SEMANTIC_GUARD"] = "off"
