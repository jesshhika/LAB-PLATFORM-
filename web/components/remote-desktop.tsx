"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

export type RemoteDesktopHandle = {
  sendText: (text: string) => boolean;
};

type ConnectionToken = {
  token: string;
  wsUrl: string;
  expiresAt: string;
};

const RemoteDesktop = forwardRef<RemoteDesktopHandle, { sessionId: string }>(
  function RemoteDesktop({ sessionId }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    const desktopRef = useRef<HTMLElement>(null);
    const guacRef = useRef<typeof import("guacamole-common-js").default | null>(null);
    const clientRef = useRef<InstanceType<
      typeof import("guacamole-common-js").default.Client
    > | null>(null);
    const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const intentionalClose = useRef(false);
    const [status, setStatus] = useState("Connecting to the lab VM…");
    const [error, setError] = useState<string | null>(null);
    const [isFullscreen, setIsFullscreen] = useState(false);

    useEffect(() => {
      const updateFullscreen = () =>
        setIsFullscreen(document.fullscreenElement === desktopRef.current);
      document.addEventListener("fullscreenchange", updateFullscreen);
      return () => document.removeEventListener("fullscreenchange", updateFullscreen);
    }, []);

    const sendText = useCallback((text: string) => {
      const client = clientRef.current;
      if (!client) return false;
      if ([...text].some((character) => {
        const code = character.codePointAt(0);
        return code === undefined || code > 0x7e;
      })) {
        return false;
      }

      const shift = 0xffe1;
      for (const character of text) {
        if (character === "\n" || character === "\r") {
          client.sendKeyEvent(1, 0xff0d);
          client.sendKeyEvent(0, 0xff0d);
          continue;
        }
        const code = character.codePointAt(0);
        if (code === undefined) return false;
        const uppercase = code >= 65 && code <= 90;
        const keysym = uppercase ? code + 32 : code;
        if (uppercase) client.sendKeyEvent(1, shift);
        client.sendKeyEvent(1, keysym);
        client.sendKeyEvent(0, keysym);
        if (uppercase) client.sendKeyEvent(0, shift);
      }
      return true;
    }, []);

    useImperativeHandle(ref, () => ({ sendText }), [sendText]);

    useEffect(() => {
      let disposed = false;
      let connected = false;
      let guac: typeof import("guacamole-common-js").default | undefined;
      intentionalClose.current = false;
      const parent = containerRef.current;
      const resizeObserver = new ResizeObserver(() => {
        const client = clientRef.current;
        if (!connected || !client || !parent) return;
        const width = parent.clientWidth;
        const height = parent.clientHeight;
        if (width > 0 && height > 0) {
          client.sendSize(width, height);
          const displayWidth = client.getDisplay().getWidth();
          const displayHeight = client.getDisplay().getHeight();
          if (displayWidth && displayHeight) {
            client.getDisplay().scale(Math.min(width / displayWidth, height / displayHeight));
          }
        }
      });
      if (parent) resizeObserver.observe(parent);

      const connect = async () => {
        try {
          const response = await fetch(
            `/api/backend/sessions/${encodeURIComponent(sessionId)}/connection-token`,
            { method: "POST", cache: "no-store" },
          );
          if (!response.ok) {
            throw new Error(`Could not get a remote desktop token (HTTP ${response.status}).`);
          }
          const data = (await response.json()) as ConnectionToken;
          if (Date.parse(data.expiresAt) <= Date.now()) {
            throw new Error("The remote desktop token expired before connection.");
          }
          guac ??= (await import("guacamole-common-js")).default;
          guacRef.current = guac;
          if (disposed || !containerRef.current) return;

          const separator = data.wsUrl.includes("?") ? "&" : "?";
          const tunnel = new guac.WebSocketTunnel(
            `${data.wsUrl}${separator}token=${encodeURIComponent(data.token)}`,
          );
          const client = new guac.Client(tunnel);
          clientRef.current = client;
          const display = client.getDisplay().getElement();
          display.tabIndex = 0;
          display.setAttribute("aria-label", "Remote Windows desktop");
          containerRef.current.replaceChildren(display);

          const mouse = new guac.Mouse(display);
          mouse.onmousedown = (state) => client.sendMouseState(state, true);
          mouse.onmouseup = (state) => client.sendMouseState(state, true);
          mouse.onmousemove = (state) => client.sendMouseState(state, true);

          const keyboard = new guac.Keyboard(display);
          keyboard.onkeydown = (keysym) => client.sendKeyEvent(1, keysym);
          keyboard.onkeyup = (keysym) => client.sendKeyEvent(0, keysym);

          client.onclipboard = (stream, mimetype) => {
            if (mimetype !== "text/plain") return;
            const reader = new guac!.StringReader(stream);
            let clipboardText = "";
            reader.ontext = (text) => {
              clipboardText += text;
            };
            reader.onend = () => {
              void navigator.clipboard?.writeText(clipboardText).catch(() => {
                setError("The browser blocked clipboard access. Check clipboard permissions.");
              });
            };
          };

          client.onstatechange = (state) => {
            if (state === guac!.Client.State.CONNECTED) {
              connected = true;
              setStatus("Connected");
              setError(null);
              resizeObserver.disconnect();
              if (parent) resizeObserver.observe(parent);
            } else if (
              state === guac!.Client.State.DISCONNECTED &&
              !intentionalClose.current &&
              !disposed
            ) {
              connected = false;
              setStatus("Reconnecting…");
              if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
              reconnectTimer.current = setTimeout(() => void connect(), 2000);
            }
          };
          client.onerror = (cause) => {
            setError(cause.message ?? "The remote desktop connection failed.");
          };
          client.connect();
        } catch (cause) {
          if (!disposed) {
            setError(cause instanceof Error ? cause.message : "The remote desktop connection failed.");
            setStatus("Disconnected");
          }
        }
      };

      void connect();
      return () => {
        disposed = true;
        intentionalClose.current = true;
        connected = false;
        resizeObserver.disconnect();
        if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
        clientRef.current?.disconnect();
        clientRef.current = null;
      };
    }, [sessionId]);

    const pasteClipboard = async () => {
      try {
        const text = await navigator.clipboard.readText();
        const client = clientRef.current;
        const guac = guacRef.current;
        if (!client || !guac) throw new Error("The remote desktop is not connected.");
        const writer = new guac.StringWriter(client.createClipboardStream("text/plain"));
        writer.sendText(text);
        writer.sendEnd();
      } catch (cause) {
        setError(
          cause instanceof Error
            ? cause.message
            : "Clipboard paste failed. Check browser permissions and desktop connectivity.",
        );
      }
    };

    const toggleFullscreen = async () => {
      try {
        if (document.fullscreenElement === desktopRef.current) {
          await document.exitFullscreen();
        } else {
          await desktopRef.current?.requestFullscreen();
        }
      } catch {
        setError("The browser could not change fullscreen mode.");
      }
    };

    return (
      <section className="flex h-full min-h-0 flex-col bg-slate-950 text-white" ref={desktopRef}>
        <div className="flex items-center justify-between border-b border-slate-700 px-3 py-2 text-sm">
          <span>{status}</span>
          <div className="flex gap-2">
            <button
              className="rounded border border-slate-600 px-2 py-1 hover:bg-slate-800"
              onClick={() => void pasteClipboard()}
              type="button"
            >
              Paste clipboard
            </button>
            <button
              className="rounded border border-slate-600 px-2 py-1 hover:bg-slate-800"
              onClick={() => void toggleFullscreen()}
              type="button"
            >
              {isFullscreen ? "Exit fullscreen" : "Fullscreen"}
            </button>
          </div>
        </div>
        {error ? <p className="bg-red-950 px-3 py-2 text-sm text-red-200">{error}</p> : null}
        <div className="relative min-h-0 flex-1 overflow-hidden" ref={containerRef} />
      </section>
    );
  },
);

export default RemoteDesktop;
