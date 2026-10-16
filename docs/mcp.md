# Use from an MCP client

`printready mcp` runs an MCP server over stdio, so any MCP client (Claude Desktop, Claude Code, or your own agent) can call printready as tools. It runs rules mode only, so no model or API key is involved and nothing costs money.

| tool | arguments | returns |
|---|---|---|
| `check_artwork` | `path`, `size_in` | overall status and one finding per check (message, measured numbers, who can fix it) |
| `fix_artwork` | `path`, `size_in`, `out_dir` (optional) | outcome, findings before and after, each fix step with its damage-guard numbers, the customer message, absolute paths of `fixed.png`, `cutline.svg`, `proof.png`, `overlay.png`, `report.json`, `report.html` |
| `get_rules` | none | every rule's value, source (Sticker Mule FAQ URL or `convention`) and a one-line reason |

`size_in` is the finished sticker's longest side in inches, border included. Without `out_dir`, outputs go next to the image in `<name>-printready/`.

## Install

```
uv sync --extra mcp
```

## Claude Desktop

Add this to `claude_desktop_config.json`, with your own path to the repo:

```json
{
  "mcpServers": {
    "printready": {
      "command": "uv",
      "args": ["--directory", "C:/path/to/printready", "run", "--extra", "mcp", "printready", "mcp"]
    }
  }
}
```

## Claude Code

```
claude mcp add printready -- uv --directory /path/to/printready run --extra mcp printready mcp
```

You can also commit the same `mcpServers` block shown above as `.mcp.json` in a project.

Then ask: "Check ~/Downloads/logo.png as a 3 inch die-cut sticker and fix it if you can."

Rules are paraphrased from Sticker Mule's public FAQ. printready is not affiliated with Sticker Mule.
