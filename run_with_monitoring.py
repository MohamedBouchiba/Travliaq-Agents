"""Wrapper pour exécuter la pipeline avec monitoring complet."""
import sys
import faulthandler
import signal
import time
import json
from pathlib import Path

# Activer le traceback détaillé pour segfaults
faulthandler.enable()

print("=" * 70)
print("TRAVLIAQ PIPELINE - MODE MONITORING")
print("=" * 70)

# Monitoring mémoire
import psutil
import os

process = psutil.Process(os.getpid())

def log_stats(label: str):
    """Log mémoire et stats système."""
    mem_info = process.memory_info()
    mem_mb = mem_info.rss / 1024 / 1024

    cpu_percent = process.cpu_percent(interval=0.1)

    print(f"\n[STATS] {label}")
    print(f"  Memory: {mem_mb:.2f} MB")
    print(f"  CPU: {cpu_percent:.1f}%")
    print(f"  Threads: {process.num_threads()}")


log_stats("Initial State")

# Charger le questionnaire
if len(sys.argv) < 2:
    print("\n[ERROR] Usage: python run_with_monitoring.py <questionnaire.json>")
    sys.exit(1)

questionnaire_path = Path(sys.argv[1])
if not questionnaire_path.exists():
    print(f"\n[ERROR] File not found: {questionnaire_path}")
    sys.exit(1)

with open(questionnaire_path) as f:
    questionnaire = json.load(f)

print(f"\n[INFO] Loaded questionnaire: {questionnaire.get('id', 'N/A')}")
log_stats("After Loading Questionnaire")

# Importer la pipeline
print("\n[INFO] Importing pipeline modules...")
try:
    from app.crew_pipeline import travliaq_crew_pipeline
    from app.services.persona_inference_service import persona_engine

    log_stats("After Imports")
    print("[OK] Imports successful")

except Exception as e:
    print(f"\n[ERROR] Failed to import: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Exécuter avec monitoring continu
import threading

monitoring_active = True
stats_history = []


def continuous_monitor():
    """Thread de monitoring continu."""
    while monitoring_active:
        mem = process.memory_info().rss / 1024 / 1024
        cpu = process.cpu_percent(interval=1)
        threads = process.num_threads()

        stats_history.append({
            "time": time.time(),
            "memory_mb": mem,
            "cpu_percent": cpu,
            "threads": threads,
        })

        # Alert si mémoire > 1GB
        if mem > 1024:
            print(f"\n[WARNING] High memory usage: {mem:.2f} MB")

        time.sleep(5)  # Check toutes les 5 secondes


print("\n[INFO] Starting continuous monitoring thread...")
monitor_thread = threading.Thread(target=continuous_monitor, daemon=True)
monitor_thread.start()

# Exécuter la pipeline
print("\n" + "=" * 70)
print("RUNNING PIPELINE")
print("=" * 70)

start_time = time.time()
result = None
error = None

try:
    log_stats("Before Pipeline Run")

    result = travliaq_crew_pipeline(
        questionnaire=questionnaire,
        persona_inference=persona_engine.infer,
        should_save=True,
    )

    log_stats("After Pipeline Run")

    elapsed = time.time() - start_time
    print(f"\n[SUCCESS] Pipeline completed in {elapsed:.2f}s")

except MemoryError as e:
    error = f"MemoryError: {e}"
    print(f"\n[ERROR] {error}")

except RecursionError as e:
    error = f"RecursionError: {e}"
    print(f"\n[ERROR] {error}")

except KeyboardInterrupt:
    error = "UserInterrupt"
    print("\n[INFO] Interrupted by user")

except Exception as e:
    error = f"{type(e).__name__}: {e}"
    print(f"\n[ERROR] {error}")
    import traceback
    traceback.print_exc()

finally:
    monitoring_active = False
    time.sleep(1)  # Attendre que le thread se termine

    # Sauvegarder les stats
    stats_file = "monitoring_stats.json"
    with open(stats_file, "w") as f:
        json.dump({
            "questionnaire_id": questionnaire.get("id"),
            "elapsed_seconds": time.time() - start_time,
            "error": error,
            "stats_history": stats_history,
            "final_memory_mb": process.memory_info().rss / 1024 / 1024,
        }, f, indent=2)

    print(f"\n[INFO] Stats saved to {stats_file}")

# Afficher résumé
print("\n" + "=" * 70)
print("MONITORING SUMMARY")
print("=" * 70)

if stats_history:
    max_mem = max(s["memory_mb"] for s in stats_history)
    avg_mem = sum(s["memory_mb"] for s in stats_history) / len(stats_history)
    max_cpu = max(s["cpu_percent"] for s in stats_history)

    print(f"Memory (peak): {max_mem:.2f} MB")
    print(f"Memory (avg): {avg_mem:.2f} MB")
    print(f"CPU (peak): {max_cpu:.1f}%")
    print(f"Samples: {len(stats_history)}")

if error:
    print(f"\n[RESULT] Failed: {error}")
    sys.exit(1)
else:
    print(f"\n[RESULT] Success")

    # Sauvegarder le résultat
    if result:
        output_file = "output_monitored.json"
        with open(output_file, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"[INFO] Output saved to {output_file}")
