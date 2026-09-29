"""
Script de diagnostic pour vérifier l'état des workspaces et KB
"""
import sys
import json
from pathlib import Path

# Ajouter le dossier racine au path pour import
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.workspaces.workspace_manager import get_workspace_manager
from src.api.dependencies import get_kb

print("=" * 80)
print("🔍 DIAGNOSTIC WORKSPACES & KB")
print("=" * 80)

# 1. Vérifier l'index des workspaces
print("\n📁 1. INDEX DES WORKSPACES")
print("-" * 80)

try:
    manager = get_workspace_manager()
    print(f"✅ WorkspaceManager initialisé")
    print(f"   Base path: {manager.base_path.absolute()}")
    print(f"   Workspaces dir: {manager.workspaces_dir.absolute()}")
    print(f"   Index file: {manager.index_path.absolute()}")
    
    if manager.index_path.exists():
        print(f"   ✅ Index existe")
        with open(manager.index_path, 'r') as f:
            index = json.load(f)
        
        print(f"\n   Active workspace: {index.get('active_workspace', 'AUCUN')}")
        print(f"   Total workspaces: {len(index.get('workspaces', []))}")
        
        for ws in index.get('workspaces', []):
            status = "🟢 ACTIF" if ws['id'] == index.get('active_workspace') else "⚪ inactif"
            print(f"     {status} {ws['id']} - {ws['name']}")
    else:
        print(f"   ❌ Index n'existe pas")
        
except Exception as e:
    print(f"❌ Erreur: {e}")
    import traceback
    traceback.print_exc()

# 2. Vérifier le workspace actif
print("\n📂 2. WORKSPACE ACTIF")
print("-" * 80)

try:
    active = manager.get_active_workspace()
    
    if active:
        print(f"✅ Workspace actif trouvé: {active.id}")
        print(f"   Nom: {active.name}")
        print(f"   Client: {active.client}")
        print(f"   Environnement: {active.environment}")
        print(f"   Stats: {active.data_stats}")
        
        # Vérifier les chemins
        ws_path = manager._get_workspace_path(active.id)
        kb_path = manager.get_workspace_kb_path(active.id)
        config_path = manager.get_workspace_config_path(active.id)
        
        print(f"\n   📍 Chemins:")
        print(f"      Workspace: {ws_path.absolute()}")
        print(f"      KB:        {kb_path.absolute()} {'✅' if kb_path.exists() else '❌ MANQUANT'}")
        print(f"      Config:    {config_path.absolute()} {'✅' if config_path.exists() else '❌ MANQUANT'}")
        
    else:
        print(f"❌ Aucun workspace actif !")
        
except Exception as e:
    print(f"❌ Erreur: {e}")
    import traceback
    traceback.print_exc()

# 3. Vérifier la KB chargée via dependencies
print("\n📚 3. KB CHARGÉE PAR DEPENDENCIES")
print("-" * 80)

try:
    kb = get_kb()
    print(f"✅ KB chargée")
    print(f"   Path: {kb.kb_path.absolute()}")
    print(f"   Existe: {'✅' if kb.kb_path.exists() else '❌ MANQUANT'}")
    
    # Stats KB
    stats = kb.get_stats()
    print(f"\n   📊 Contenu KB:")
    print(f"      Version: {stats.get('version')}")
    print(f"      Droits socles : {stats.get('birth_rights_count', 0)}")
    print(f"      Rôles validés: {stats.get('validated_roles_total', 0)}")
    print(f"         - Applicatifs: {stats.get('validated_roles_by_type', {}).get('APPLICATIF', 0)}")
    print(f"         - Métier: {stats.get('validated_roles_by_type', {}).get('METIER', 0)}")
    print(f"      Rôles rejetés: {stats.get('rejected_roles_count', 0)}")
    print(f"      Mining runs: {stats.get('mining_runs_count', 0)}")
    
except Exception as e:
    print(f"❌ Erreur: {e}")
    import traceback
    traceback.print_exc()

# 4. Vérifier la KB globale (fallback)
print("\n🌍 4. KB GLOBALE (FALLBACK)")
print("-" * 80)

global_kb_path = Path("knowledge_base.json")
print(f"Path: {global_kb_path.absolute()}")
print(f"Existe: {'✅' if global_kb_path.exists() else '❌ MANQUANT'}")

if global_kb_path.exists():
    try:
        with open(global_kb_path, 'r') as f:
            global_kb = json.load(f)
        
        print(f"\n📊 Contenu KB globale:")
        print(f"   Rôles validés: {len(global_kb.get('validated_roles', []))}")
        print(f"   Rôles rejetés: {len(global_kb.get('rejected_roles', []))}")
    except Exception as e:
        print(f"❌ Erreur lecture: {e}")

# 5. DIAGNOSTIC FINAL
print("\n" + "=" * 80)
print("🎯 DIAGNOSTIC FINAL")
print("=" * 80)

try:
    kb = get_kb()
    active = manager.get_active_workspace() if 'manager' in locals() else None
    
    if active and kb.kb_path == manager.get_workspace_kb_path(active.id):
        print("✅ CORRECT: KB chargée depuis workspace actif")
        print(f"   Workspace: {active.id}")
        print(f"   KB: {kb.kb_path}")
    elif kb.kb_path == Path("knowledge_base.json"):
        print("⚠️ PROBLÈME: KB chargée depuis fichier GLOBAL au lieu du workspace !")
        print(f"   KB actuelle: {kb.kb_path}")
        if active:
            print(f"   KB attendue: {manager.get_workspace_kb_path(active.id)}")
            print(f"\n   🔧 SOLUTION: Vérifier pourquoi get_kb() fallback sur KB globale")
    else:
        print("❓ INCONNU: KB chargée depuis un chemin inattendu")
        print(f"   KB: {kb.kb_path}")
        
except Exception as e:
    print(f"❌ Erreur finale: {e}")

print("\n" + "=" * 80)
