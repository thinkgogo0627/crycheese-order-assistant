"""서버 입구. Vercel이 app/main.py 의 `app`을 자동 인식.

[호진 전용] 조원은 이 파일을 수정하지 않는다. 기능 추가는 features/registry.py 에 한 줄.
registry 에 등록된 기능마다 POST /api/{name} 이 자동 생성된다. (body = Scenario)
"""
from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import data, errors
from app.core.scenario import Scenario
from app.features import registry

app = FastAPI(title="식자재 발주 의사결정 지원")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:5173",
    allow_methods=["*"],
    allow_headers=["*"],
)
errors.install(app)


@app.get("/")
def root():
    return {"service": "식자재 관리 및 발주 자동화", "status": "ok", "docs": "/docs"}


@app.get("/health")
def health():
    return {"ok": True, "tables": data.summary()}


@app.get("/api/features")
def list_features():
    """등록된 기능 목록 (프론트·디버깅용)."""
    return [
        {"name": f.name, "label": f.label, "description": f.description, "path": f"/api/{f.name}"}
        for f in registry.FEATURES.values()
    ]


def _add_route(name: str) -> None:
    f = registry.FEATURES[name]

    def endpoint(sc: Scenario = Body(default_factory=Scenario)):
        return registry.run(name, sc)

    app.post(
        f"/api/{name}",
        response_model=f.Response,
        summary=f.label,
        description=f.description,
        name=name,
        tags=["features"],
    )(endpoint)


for _name in registry.FEATURES:
    _add_route(_name)
