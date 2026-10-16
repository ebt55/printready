"""The local workbench (`printready serve`), label mode and the static export (chunk K10).

Layout:
    paths.py        where the repo, samples, demo folder, static files and run store live
    server.py       stdlib ThreadingHTTPServer: routing, static files, JSON, SSE, upload cap;
                    serve(label_dir=..., label_pass=...) is what `printready realset label` calls
    api.py          the JSON API (one method per endpoint), shared by the server and the tests
    runs.py         run store under out/workbench/<run-id>/, event log, RunView builder
    runner.py       the ONE adapter to pipeline.run_rules / agent.run_agent (imported lazily)
    demo.py         `--demo`: replays saved runs from examples/samples/demo/, rebuilds that folder
    demo_script.py  the scripted model behind demo runs (real tools, llm's fake provider)
    samples.py      procedural sample artwork (examples/samples/*.png)
    label.py        blind keypress labelling session (labels.jsonl, append-only)
    results.py      bench metrics and real-set readers for the Results screen
    state.py        /api/state: profile, models, prices, spend ledger
    export.py       `printready site build`: static read-only copy that opens from file://

The web layer treats every pipeline object as a JSON dict (RunResult.to_dict() etc.).
"""
