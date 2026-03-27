/* global Terminal, FitAddon, Unicode11Addon, WebLinksAddon, io */
/* eslint no-unused-vars: "error", no-undef: "error" */
"use strict";

window.onload = function () {
  const term = new Terminal({
    allowProposedApi: true, // Unicode11Addon uses proposed API
    theme: {},
  });

  const fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);

  const unicode11Addon = new Unicode11Addon.Unicode11Addon();
  term.loadAddon(unicode11Addon);
  term.unicode.activeVersion = "11";

  const webLinkHandler = function (e, uri) {
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
  const socket = io({
    path: basePath + "/sio",
    transports: ["polling", "websocket"],
    reconnection: false,
    auth: { cols: term.cols, rows: term.rows },
  });

  // Push the current terminal size on connect.
  socket.on("connect", () => {
    socket.emit("resize", { cols: term.cols, rows: term.rows });
  });

  socket.on("output", (data) => {
    term.write(data);
  });

  term.onData((data) => {
    socket.emit("input", data);
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
    term.write("\r\n\x1b[7m" + msg + "\x1b[m"); // reverse video
  }

  let closedByServer = false;

  socket.on("close-connection", (reason) => {
    closedByServer = true;
    displayMessage(
      "connection closed: " + (reason || "no reason given by server"),
    );
    socket.close();
  });

  socket.on("disconnect", (reason) => {
    if (!closedByServer) {
      displayMessage("disconnected: " + reason);
    }
  });

  window.addEventListener("beforeunload", () => {
    socket.close();
  });

  let resizeTimer = null;
  const resizeObserver = new ResizeObserver(() => {
    fitAddon.fit();
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      socket.emit("resize", { cols: term.cols, rows: term.rows });
    }, 100);
  });
  resizeObserver.observe(container);
};
