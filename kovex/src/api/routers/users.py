from fastapi import APIRouter, Depends
from src.api.dependencies import get_data_loader
from src.core.data.loader import DataLoader

router = APIRouter()

@router.get("/users")
def read_users(loader: DataLoader = Depends(get_data_loader)):
    # On transforme le tableau Panda en liste d'objets simple pour le web
    # .head(100) pour ne pas tout afficher d'un coup pour le test
    data = loader.identities.head(100).to_dict(orient="records")
    return data

@router.get("/users/count")
def count_users(loader: DataLoader = Depends(get_data_loader)):
    return {"total": len(loader.identities)}