#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""더블클릭으로 여는 메뉴 — 터미널을 쓸 수 없는 환경용.

회사 정책으로 PowerShell 이나 명령 프롬프트가 막혀 있어도, 파이썬이 깔려 있으면
이 파일을 **더블클릭**하는 것만으로 돌릴 수 있다. 명령을 칠 일이 없다.

무엇이 열리지 않거나 창이 곧바로 닫히면 GETTING_STARTED_windows.md 를 보세요.
"""
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
SC = os.path.join(ROOT, "scripts")
sys.path.insert(0, SC)

try:
    import _console
    _console.setup()
except Exception:
    pass

MENU = """
==========================================================
  레딧 재수집 — 무엇을 할까요?
==========================================================

  1)  환경 진단          무엇이 빠졌는지 먼저 확인합니다
  2)  GV80 재수집        수집 -> 파싱 -> 검증까지
  3)  G70 재수집         (GV80 이 끝난 뒤에)

  4)  접속 정보 입력      settings.txt 를 메모장으로 엽니다
  5)  결과 폴더 열기      work 폴더를 탐색기로 엽니다

  0)  닫기

  ※ 2번은 중간에 끊겨도 됩니다. 다시 2번을 고르면 이어서 받습니다.
"""


def pause(msg="\n엔터를 누르면 메뉴로 돌아갑니다... "):
    try:
        input(msg)
    except (EOFError, KeyboardInterrupt):
        pass


def run(cmd_args, title):
    print("\n" + "=" * 58)
    print("  " + title)
    print("=" * 58 + "\n")
    try:
        subprocess.run([sys.executable] + cmd_args, cwd=ROOT)
    except KeyboardInterrupt:
        print("\n\n중단했습니다. 받다 만 곳까지는 저장돼 있습니다 —")
        print("다시 같은 번호를 고르면 이어서 받습니다.")
    except Exception as e:
        print("\n실행하지 못했습니다: %s" % e)
        print("이 화면을 통째로 복사해서 물어보시면 됩니다.")


def open_in_explorer(path):
    try:
        if hasattr(os, "startfile"):                 # 윈도우
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
        print("\n열었습니다: %s" % path)
        print("창이 안 보이면 작업 표시줄을 확인하세요.")
    except Exception as e:
        print("\n열지 못했습니다: %s" % e)
        print("직접 찾아가세요: %s" % path)


def main():
    try:
        import _settings
        p, created = _settings.ensure(ROOT)
        if created:
            print("접속 정보 파일을 새로 만들었습니다: %s" % p)
            print("4번을 골라 내용을 채우세요.")
    except Exception:
        p = os.path.join(ROOT, "settings.txt")

    while True:
        print(MENU)
        try:
            pick = input("  번호를 누르고 엔터: ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if pick == "1":
            run([os.path.join(SC, "recollect.py"), "doctor"], "환경 진단")
            pause()
        elif pick == "2":
            run([os.path.join(SC, "recollect.py"), "gv80"], "GV80 재수집")
            pause()
        elif pick == "3":
            run([os.path.join(SC, "recollect.py"), "g70"], "G70 재수집")
            pause()
        elif pick == "4":
            open_in_explorer(p)
            print("\n값을 채우고 저장한 뒤, 1번(환경 진단)으로 확인하세요.")
            pause()
        elif pick == "5":
            w = os.path.join(ROOT, "work")
            os.makedirs(w, exist_ok=True)
            open_in_explorer(w)
            pause()
        elif pick in ("0", "q", "Q", ""):
            return
        else:
            print("\n0~5 중에서 골라 주세요.")
            pause()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 더블클릭으로 열었을 때 창이 그냥 사라지면 원인을 볼 수 없다.
        import traceback
        print("\n예상하지 못한 오류가 났습니다. 아래를 통째로 복사해 물어보세요.\n")
        traceback.print_exc()
        pause("\n엔터를 누르면 닫힙니다... ")
