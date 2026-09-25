# terminalserver

A web-based terminal using [xterm.js](https://xtermjs.org/),
[WebSocket](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket),
and [Uvicorn](https://www.uvicorn.org/).
The client renders the terminal with xterm.js.  Communication between the
client and server is handled by WebSocket.  The server spawns a PTY shell
and relays input from xterm.js to the shell and output from the shell back
to xterm.js.

The WebSocket endpoint is `/ws`. Messages use JSON objects with a `type` field:
`input`, `resize`, `output`, and `close-connection`.

## System Requirements

- Server side: Linux with Python 3.12+
- Client side: Any modern browser

The server dependencies include Uvicorn's WebSocket support.

## Quick Start

```
make run-test
```

This downloads the required Python packages and starts the server on
`http://localhost:9000/`.  Open the URL in a browser to access the terminal.

Edit `config.jsonc` to change the shell path, arguments, and environment.
JSONC supports `//` and `/* ... */` comments, as well as trailing commas.
See the `Makefile` for other operations (`make usage`).

## Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
