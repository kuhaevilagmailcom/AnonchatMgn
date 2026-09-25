(() => {
  'use strict';

  class AnonRealtime {
    constructor({ baseUrl = '', initData = '', onEvent = () => {}, onState = () => {} } = {}) {
      this.baseUrl = String(baseUrl || '').replace(/\/$/, '');
      this.initData = String(initData || '');
      this.onEvent = onEvent;
      this.onState = onState;
      this.ws = null;
      this.connected = false;
      this.closed = false;
      this.retry = 0;
      this.retryTimer = null;
      this.pingTimer = null;
    }

    _url() {
      const origin = this.baseUrl || window.location.origin;
      return origin.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:') + '/api/miniapp/ws';
    }

    start() {
      if (this.closed || !this.initData || this.ws) return;
      this._connect();
    }

    stop() {
      this.closed = true;
      clearTimeout(this.retryTimer);
      clearInterval(this.pingTimer);
      this.retryTimer = null;
      this.pingTimer = null;
      try { this.ws?.close(1000, 'client stop'); } catch (_) {}
      this.ws = null;
      this.connected = false;
    }

    _setConnected(value) {
      if (this.connected === value) return;
      this.connected = value;
      this.onState(value);
    }

    _scheduleReconnect() {
      if (this.closed) return;
      const delay = Math.min(15000, 700 * Math.pow(1.7, this.retry++));
      clearTimeout(this.retryTimer);
      this.retryTimer = setTimeout(() => this._connect(), delay);
    }

    _connect() {
      if (this.closed || this.ws) return;
      let ws;
      try { ws = new WebSocket(this._url()); }
      catch (_) { this._scheduleReconnect(); return; }
      this.ws = ws;

      ws.addEventListener('open', () => {
        this.retry = 0;
        try { ws.send(JSON.stringify({ type: 'auth', initData: this.initData })); }
        catch (_) {}
      });

      ws.addEventListener('message', event => {
        let data;
        try { data = JSON.parse(event.data); } catch (_) { return; }
        if (data?.type === 'ready') {
          this._setConnected(true);
          clearInterval(this.pingTimer);
          this.pingTimer = setInterval(() => {
            if (this.ws?.readyState === WebSocket.OPEN) {
              try { this.ws.send(JSON.stringify({ type: 'ping' })); } catch (_) {}
            }
          }, 20000);
        }
        this.onEvent(data || {});
      });

      ws.addEventListener('close', () => {
        clearInterval(this.pingTimer);
        this.pingTimer = null;
        this.ws = null;
        this._setConnected(false);
        this._scheduleReconnect();
      });

      ws.addEventListener('error', () => {
        try { ws.close(); } catch (_) {}
      });
    }
  }

  window.AnonRealtime = AnonRealtime;
})();
