"""Executa o pipeline completo: coleta -> tratamento -> mineracao."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import coleta, tratamento, mineracao  # noqa: E402

for etapa in (coleta, tratamento, mineracao):
    t = time.time()
    print(f"\n===== {etapa.__name__.upper()} =====")
    etapa.main()
    print(f"[{etapa.__name__}] {time.time() - t:.1f}s")
