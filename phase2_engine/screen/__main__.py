import multiprocessing

if __name__ == "__main__":
    # EXE（PyInstaller）で名簿づくりの子のプロセスを起こせるように（game_core/roster_parallel.py）
    multiprocessing.freeze_support()
    from phase2_engine.screen.app import main

    main()
