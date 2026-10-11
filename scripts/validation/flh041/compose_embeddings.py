"""FLH-043 counted embedding fixture inside an owned Compose network only."""
import json
import os
from pathlib import Path
import threading
import time
import fake_embeddings

# Only this disposable container needs a container-interface listener. Host
# publication is 127.0.0.1, controlled by the runner. Original fixture unchanged.
OriginalServer = fake_embeddings.ThreadingHTTPServer
class ContainerServer(OriginalServer):
    def __init__(self, address, handler):
        super().__init__(("0.0.0.0", 9000), handler)
fake_embeddings.ThreadingHTTPServer = ContainerServer

ledger = Path("/output/compose-provider.json")
with fake_embeddings.FakeEmbeddings(dimensions=8) as provider:
    for doc in json.loads(Path("/inputs/documents.json").read_text()):
        provider.register(doc["Text"], "document")
    provider.register("flh043 query", "query")
    print("fixture-ready", flush=True)
    while True:
        temporary = ledger.with_suffix(".new")
        temporary.write_text(json.dumps(provider.snapshot()))
        os.replace(temporary, ledger)
        time.sleep(0.05)
