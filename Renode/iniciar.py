"""Copia o firmware compilado e inicia o Renode no Windows."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


DIRETORIO_RENODE = Path(__file__).resolve().parent
RAIZ_PROJETO = DIRETORIO_RENODE.parent


def main():
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument(
        "--executavel", type=Path,
        default=Path(r"C:\Program Files\Renode\renode.exe"),
        help="caminho do executavel do Renode",
    )
    argumentos = analisador.parse_args()
    unidade_criada = False
    try:
        if os.name != "nt":
            raise ValueError("Este iniciador usa a unidade R: do Windows, conforme executar.resc.")
        firmware = RAIZ_PROJETO / "Debug" / "Particle Filter.elf"
        if not firmware.is_file():
            raise ValueError(f"Firmware nao encontrado: {firmware}. Compile o projeto primeiro.")
        if not argumentos.executavel.is_file():
            raise ValueError(f"Renode nao encontrado: {argumentos.executavel}. Use --executavel.")
        if Path("R:/").exists():
            raise ValueError("A unidade R: ja esta em uso. Libere-a antes de iniciar o Renode.")
        shutil.copy2(firmware, DIRETORIO_RENODE / "firmware.elf")
        subprocess.run(["subst", "R:", str(RAIZ_PROJETO)], check=True)
        unidade_criada = True
        return subprocess.run([str(argumentos.executavel), r"R:\Renode\executar.resc"]).returncode
    except (OSError, ValueError, subprocess.CalledProcessError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    finally:
        if unidade_criada:
            subprocess.run(["subst", "R:", "/D"], check=False)


if __name__ == "__main__":
    sys.exit(main())
