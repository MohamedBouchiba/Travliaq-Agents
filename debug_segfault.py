"""Script pour déboguer le Segmentation Fault."""
import sys
import traceback
import faulthandler
import resource

# Activer le traceback détaillé pour les segfaults
faulthandler.enable()

print("=" * 60)
print("DEBUG SEGMENTATION FAULT")
print("=" * 60)

# Limites système
try:
    # Sur Windows, resource n'est pas disponible
    if hasattr(resource, 'getrlimit'):
        soft, hard = resource.getrlimit(resource.RLIMIT_STACK)
        print(f"Stack limit: {soft} / {hard}")

        mem_soft, mem_hard = resource.getrlimit(resource.RLIMIT_AS)
        print(f"Memory limit: {mem_soft} / {mem_hard}")
except Exception as e:
    print(f"Resource limits not available on Windows: {e}")

# Limites Python
print(f"Python recursion limit: {sys.getrecursionlimit()}")
print(f"Python version: {sys.version}")

# Taille mémoire actuelle
import psutil
import os

process = psutil.Process(os.getpid())
mem_info = process.memory_info()
print(f"Current memory usage: {mem_info.rss / 1024 / 1024:.2f} MB")

print("\n" + "=" * 60)
print("Tentative de reproduction du bug...")
print("=" * 60)

try:
    # Importer les modules qui pourraient causer le crash
    from app.crew_pipeline.pipeline import TravelPlannerCrew

    print("[OK] Imports successful")

    # Simuler un questionnaire minimal
    questionnaire = {
        "id": "debug-test",
        "email": "test@example.com",
        "destination": "Paris",
        "date_depart": "15/12/2025",
        "date_retour": "22/12/2025",
        "nombre_voyageurs": 2,
        "nuits_exactes": 7,
    }

    print("[INFO] Starting pipeline with minimal questionnaire...")

    # Créer la pipeline
    crew = TravelPlannerCrew(verbose=True)

    print("[OK] Crew created successfully")

    # Lancer avec monitoring mémoire
    print("\n[INFO] Running crew.run()...")
    print("[INFO] Monitoring memory during execution...\n")

    import threading
    import time

    def monitor_memory():
        """Thread pour monitorer la mémoire pendant l'exécution."""
        while monitoring_active:
            mem = process.memory_info().rss / 1024 / 1024
            print(f"[MEM] Current: {mem:.2f} MB")
            time.sleep(5)

    monitoring_active = True
    monitor_thread = threading.Thread(target=monitor_memory, daemon=True)
    monitor_thread.start()

    try:
        result = crew.run(questionnaire=questionnaire)
        print("\n[SUCCESS] Pipeline completed without crash!")
        print(f"Result keys: {result.keys() if isinstance(result, dict) else 'N/A'}")
    finally:
        monitoring_active = False

except KeyboardInterrupt:
    print("\n[INFO] Interrupted by user")
    sys.exit(0)

except Exception as e:
    print(f"\n[ERROR] Exception caught: {type(e).__name__}")
    print(f"Message: {e}")
    traceback.print_exc()

    # Dump de la pile d'appels
    print("\n" + "=" * 60)
    print("STACK TRACE")
    print("=" * 60)
    faulthandler.dump_traceback()

    sys.exit(1)

print("\n" + "=" * 60)
print("Script completed successfully - no segfault detected")
print("=" * 60)

# Afficher l'utilisation mémoire finale
final_mem = process.memory_info().rss / 1024 / 1024
print(f"Final memory usage: {final_mem:.2f} MB")
