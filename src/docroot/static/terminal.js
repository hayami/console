/* global Terminal, FitAddon, Unicode11Addon, WebLinksAddon */
/* eslint no-unused-vars: "error", no-undef: "error" */
"use strict";

window.addEventListener("load", () => {
  const clientOptions = {
    unicodeVersion: "11"
  };
  const terminalOptions = {
    cursorBlink: false,
    cursorInactiveStyle: "outline",
    cursorStyle: "block",
    fontFamily: "'Noto Sans Mono', 'Kosugi Maru', 'monospace'",
    fontSize: 14,
    fontWeight: "500",
    fontWeightBold: "700",
    macOptionIsMeta: true,
    theme: {
      background: "#f0f0ca",
      foreground: "#353535",
      cursor: "#d33333",
      cursorAccent: "#f0f0ca",
      selectionBackground: "#d7d7d7",
      selectionInactiveBackground: "#d7d7d7",
      selectionForeground: "#353535",
      black: "#f0f0ca",
      red: "#a8334c",
      green: "#4f6c31",
      yellow: "#944927",
      blue: "#286486",
      magenta: "#88507d",
      cyan: "#3b8992",
      white: "#353535",
      brightBlack: "#acac89",
      brightRed: "#94253e",
      brightGreen: "#3f5a22",
      brightYellow: "#803d1c",
      brightBlue: "#1d5573",
      brightMagenta: "#7b3b70",
      brightCyan: "#2b747c",
      brightWhite: "#5c5c5c",
    },
  };

  const term = new Terminal({
    allowProposedApi: true, // Unicode11Addon uses proposed API
    ...terminalOptions, // theme: {},
  });

  const fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);

  const unicode11Addon = new Unicode11Addon.Unicode11Addon();
  term.loadAddon(unicode11Addon);
  term.unicode.activeVersion = clientOptions.unicodeVersion;

  const webLinkHandler = (e, uri) => {
    if (!e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) return;
    const newWindow = window.open();
    if (newWindow) {
      try {
        newWindow.opener = null;
      } catch {
        // no-op
      }
      newWindow.location.href = uri;
    } else {
      console.warn("Opening link blocked as opener could not be cleared");
    }
  };
  const webLinksAddon = new WebLinksAddon.WebLinksAddon(webLinkHandler);
  term.loadAddon(webLinksAddon);

  const container = document.getElementById("terminal-container");
  term.open(container);
  term.focus();
  fitAddon.fit();

  const basePath = location.pathname.replace(/\/+$/, "");
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(
    `${protocol}//${location.host}${basePath}/ws` +
      `?cols=${term.cols}&rows=${term.rows}`,
  );

  // Push the current terminal size on connect.
  socket.addEventListener("open", () => {
    socket.send(
      JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }),
    );
  });

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "output") {
      term.write(message.data);
    }
  });

  term.onData((data) => {
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "input", data }));
    }
  });

  term.onSelectionChange(() => {
    const text = term.getSelection();
    if (!text) return;
    const trimmed = text
      .split("\n")
      .map((line) => line.trimEnd())
      .join("\n");
    navigator.clipboard.writeText(trimmed).catch(() => {});
  });

  function displayMessage(msg) {
    console.log(msg);
    term.write(`\r\n\x1b[7m${msg}\x1b[m`); // reverse video
  }

  socket.addEventListener("close", (event) => {
    displayMessage(
      `connection closed (${event.code}): ${event.reason || "connection closed"}`,
    );
  });

  window.addEventListener("beforeunload", () => {
    socket.close();
  });

  let resizeTimer = null;
  const resizeObserver = new ResizeObserver(() => {
    fitAddon.fit();
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(
          JSON.stringify({
            type: "resize",
            cols: term.cols,
            rows: term.rows,
          }),
        );
      }
    }, 100);
  });
  resizeObserver.observe(container);
});
