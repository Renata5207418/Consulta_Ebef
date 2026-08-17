import os
import platform
import sys
from pathlib import Path


def preparar_ambiente_sqlanywhere():
    """
    Prepara o ambiente do SQL Anywhere no Linux.

    No Windows não faz nada.
    No Linux, relança o Python uma única vez com LD_LIBRARY_PATH correto.
    Mantém a raiz do projeto no PYTHONPATH para comandos como:
    python -m automacao.scheduler
    """

    if platform.system().lower() == "windows":
        return

    sqlany_home = os.getenv("SQLANY_HOME", "/opt/sqlanywhere17")

    lib64_path = os.path.join(sqlany_home, "lib64")
    bin64_path = os.path.join(sqlany_home, "bin64")

    if not os.path.exists(lib64_path):
        return

    env = os.environ.copy()

    ld_library_path = env.get("LD_LIBRARY_PATH", "")

    paths = [
        lib64_path,
        bin64_path,
    ]

    for path in paths:
        if path and path not in ld_library_path.split(":"):
            ld_library_path = f"{path}:{ld_library_path}" if ld_library_path else path

    env["LD_LIBRARY_PATH"] = ld_library_path
    env["SQLANY17"] = sqlany_home
    env["SQLANY_HOME"] = sqlany_home

    project_root = str(Path(__file__).resolve().parents[1])
    pythonpath_atual = env.get("PYTHONPATH", "")

    if project_root not in pythonpath_atual.split(os.pathsep):
        env["PYTHONPATH"] = (
            f"{project_root}{os.pathsep}{pythonpath_atual}"
            if pythonpath_atual
            else project_root
        )

    if os.environ.get("SQLANY_ENV_READY") == "1":
        os.environ.update(env)
        return

    env["SQLANY_ENV_READY"] = "1"

    os.execvpe(
        sys.executable,
        [sys.executable] + sys.argv,
        env
    )
