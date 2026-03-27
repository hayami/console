# console

A web-based terminal using [xterm.js](https://xtermjs.org/),
[Socket.IO](https://socket.io/), and [Uvicorn](https://www.uvicorn.org/).
The client renders the terminal with xterm.js.  Communication between the
client and server is handled by Socket.IO.  The server spawns a PTY shell
and relays input from xterm.js to the shell and output from the shell back
to xterm.js.

The primary goal of this implementation is to operate behind a reverse proxy
that does not forward WebSocket connections. Socket.IO can transport data
without WebSocket.

## System Requirements

- Server side: FreeBSD or Linux with Python 3.12+
- Client side: Any modern browser

## Quick Start

```
make run
```

This downloads the required Python packages and starts the server on
`http://127.0.0.1:9000/`.  Open the URL in a browser to access the terminal.

Edit `config.json` to change the shell path, arguments, and environment.
See the `Makefile` for other operations (`make usage`).

## Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
