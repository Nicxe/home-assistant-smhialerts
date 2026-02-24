// Använd HA:s inbyggda Lit om tillgängligt, annars fallback till CDN
const getLit = async () => {
  // Home Assistant 2023.4+ exponerar Lit globalt
  if (window.LitElement && window.litHtml) {
    return {
      LitElement: window.LitElement,
      html: window.litHtml.html,
      css: window.litHtml.css,
    };
  }
  // Fallback för äldre HA-versioner eller fristående testning
  return import('https://unpkg.com/lit@3.1.0?module');
};

const { LitElement, html, css } = await getLit();

const fireIcon = new URL('./fire.svg', import.meta.url).href;
const waterShortageIcon = new URL('./waterShortage.svg', import.meta.url).href;
const temperatureIcon = new URL('./temperature.svg', import.meta.url).href;
const yellowWarningIcon = new URL('./yellowWarning.svg', import.meta.url).href;
const orangeWarningIcon = new URL('./orangeWarning.svg', import.meta.url).href;
const redWarningIcon = new URL('./redWarning.svg', import.meta.url).href;

const LEAFLET_CSS_HREF = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
const LEAFLET_JS_SRC = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
const LEAFLET_ESM_URL = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet-src.esm.js';

class SmhiAlertCard extends LitElement {
  static properties = {
    hass: {},
    config: {},
    _expanded: {},
  };

  static styles = css`
    :host {
      /* Strength of the severity-tinted background when enabled (used in color-mix) */
      --smhi-alert-bg-strong: 22%;
      --smhi-alert-bg-soft: 12%;
      /* Optical vertical adjustment for the title in compact (1-row) mode */
      --smhi-alert-compact-title-offset: 2px;
      /* Outer horizontal padding for the list (set to 0 to align with other cards) */
      --smhi-alert-outer-padding: 0px;
      display: block;
    }

    ha-card {
      /* Keep the container tight so stacking multiple transparent cards doesn't show "gaps" */
      padding: 0;
      background: transparent;
      box-shadow: none;
      border: none;
      --ha-card-background: transparent;
      --ha-card-border-width: 0;
      --ha-card-border-color: transparent;
    }
    .alerts {
      display: flex;
      flex-direction: column;
      gap: 8px;
      /* No vertical padding: otherwise it becomes visible whitespace between stacked cards */
      padding: 0 var(--smhi-alert-outer-padding, 0px);
    }
    .area-group {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .alert {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 12px;
      align-items: start;
      padding: 12px;
      border-radius: var(--smhi-alert-border-radius, 8px);
      border: 1px solid var(--divider-color);
      background: var(--card-background-color);
      position: relative;
    }
    /* Compact (single-line) layout: vertically center the whole row */
    .alert.compact {
      align-items: center;
    }

    /* Optional severity-tinted background (keeps normal card background as base) */
    .alert.bg-severity {
      background: linear-gradient(
          90deg,
          color-mix(in srgb, var(--smhi-accent) var(--smhi-alert-bg-strong, 22%), var(--card-background-color)) 0%,
          color-mix(in srgb, var(--smhi-accent) var(--smhi-alert-bg-soft, 12%), var(--card-background-color)) 55%,
          var(--card-background-color) 100%
        );
    }
    .alert::before {
      content: '';
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      width: 4px;
      border-top-left-radius: inherit;
      border-bottom-left-radius: inherit;
      background: var(--smhi-accent, var(--primary-color));
    }
    .alert.sev-yellow { --smhi-accent: var(--smhi-alert-yellow, #f1c40f); }
    .alert.sev-orange { --smhi-accent: var(--smhi-alert-orange, #e67e22); }
    .alert.sev-red { --smhi-accent: var(--smhi-alert-red, var(--error-color, #e74c3c)); }
    .alert.sev-message { --smhi-accent: var(--smhi-alert-message, var(--primary-color)); }

    .icon {
      width: 32px;
      height: 32px;
      margin-inline-start: 4px;
      margin-top: 2px;
    }
    .icon-col {
      display: flex;
      align-items: flex-start;
    }
    .icon-col.compact {
      align-items: center;
    }
    .content {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
    }
    /* Allow the content column to fill the alert height in normal (multi-line) layout */
    .content {
      align-self: stretch;
    }
    /* In compact layout, don't stretch the content; let the grid center it precisely */
    .content.compact {
      align-self: center;
    }
    .title {
      display: flex;
      gap: 8px;
      align-items: center;
      min-width: 0;
    }
    .district {
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1 1 auto;
      min-width: 0;
    }
    /* In compact mode, apply a tiny optical offset so the text looks centered */
    .district.compact {
      transform: translateY(var(--smhi-alert-compact-title-offset, 1px));
      line-height: 1;
    }
    .meta {
      color: var(--secondary-text-color);
      font-size: 0.9em;
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
    }
    .details {
      margin-top: 6px;
    }
    .md-text {
      white-space: pre-wrap;
      line-height: 1.5;
      font-family: inherit;
      font-size: 0.95em;
      color: var(--primary-text-color);
      overflow-wrap: anywhere;
    }
    .details-text {
      display: flex;
      flex-direction: column;
      gap: 12px;
      line-height: 1.5;
      font-family: inherit;
      font-size: 0.95em;
      color: var(--primary-text-color);
      overflow-wrap: anywhere;
    }
    .details-section {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .details-heading {
      font-weight: 600;
      font-size: 1em;
    }
    .details-paragraph {
      margin: 0;
    }
    .details-list {
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 6px;
    }
    .details-list li {
      margin: 0;
    }
    .details-toggle {
      color: var(--primary-color);
      cursor: pointer;
      user-select: none;
      font-size: 0.95em;
      margin-bottom: 6px;
    }
    .toggle-col {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      margin-left: auto;
    }
    .toggle-col.compact {
      align-items: center;
    }
    /* Compact toggle when placed in the right column (prevents it from consuming an extra line) */
    .details-toggle.compact {
      margin: 0;
      font-size: 0.9em;
      white-space: nowrap;
    }
    /* Ensure consistent spacing when details are expanded */
    .details .meta + .md-text,
    .details .meta + .details-text { margin-top: 6px; }

    /* Optional minimap (Leaflet) */
    .map-wrap {
      margin-top: 10px;
      border-radius: var(--smhi-alert-border-radius, 8px);
      overflow: hidden;
      border: 1px solid var(--divider-color);
      background: var(--card-background-color);
      position: relative;
      /* Prevent Leaflet's high z-index panes/controls from escaping above HA dialogs/menus */
      z-index: 0;
      isolation: isolate;
    }
    .geo-map {
      width: 100%;
      aspect-ratio: var(--smhi-alert-map-aspect, 16 / 9);
      height: auto;
      min-height: var(--smhi-alert-map-min-height, 140px);
      max-height: var(--smhi-alert-map-max-height, 260px);
      /* Leaflet attaches panes/controls with high z-index; lock them into this local stacking context */
      position: relative;
      z-index: 0 !important;
    }
    .geo-map.leaflet-container { z-index: 0 !important; }
    /* Keep Leaflet controls above map tiles (but still inside the local stacking context) */
    .geo-map .leaflet-top,
    .geo-map .leaflet-bottom { z-index: 1000 !important; }
    .geo-map .leaflet-control { z-index: 1000 !important; }
    .map-status {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.9em;
      color: var(--secondary-text-color);
      background: color-mix(in srgb, var(--card-background-color) 85%, transparent);
      pointer-events: none;
      opacity: 0;
      transition: opacity 120ms ease;
    }
    .map-status.show {
      opacity: 1;
    }
    /* Leaflet controls: allow zoom buttons, hide attribution to keep the card clean */
    .geo-map .leaflet-control-attribution { display: none; }
    .geo-map .leaflet-control-zoom {
      box-shadow: none;
      border: 1px solid var(--divider-color);
      border-radius: 6px;
      overflow: hidden;
      margin: 8px;
    }
    .geo-map .leaflet-control-zoom a {
      background: color-mix(in srgb, var(--card-background-color) 92%, transparent);
      color: var(--primary-text-color);
      border-bottom: 1px solid var(--divider-color);
    }
    .geo-map .leaflet-control-zoom a:last-child { border-bottom: none; }
    .empty {
      color: var(--secondary-text-color);
      padding: 8px var(--smhi-alert-outer-padding, 0px);
    }

    /* Editor-only controls */
    .meta-fields { margin: 12px 0; padding: 0 12px; }
    .meta-row { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 8px; padding: 6px 0; }
    .order-actions { display: flex; gap: 6px; }
    .order-btn { background: var(--secondary-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color); border-radius: 4px; padding: 2px 6px; cursor: pointer; }
    .order-btn[disabled] { opacity: 0.4; cursor: default; }
    .meta-divider-row { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 8px; padding: 6px 0; color: var(--secondary-text-color); }
    .meta-divider { border-top: 1px dashed var(--divider-color); height: 0; }
  `;

  constructor() {
    super();
    this._maps = new Map();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    // Rensa timers för att undvika minnesläckor
    clearTimeout(this._holdTimer);
    clearTimeout(this._tapTimer);
    // Rensa Leaflet-kartinstanser
    for (const [, entry] of this._maps.entries()) {
      try {
        entry?.map?.remove?.();
      } catch (e) {
        // Ignorera fel vid cleanup
      }
    }
    this._maps.clear();
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('You must specify an entity.');
    }
    const normalized = this._normalizeConfig(config);
    this.config = normalized;
    this._expanded = {};
  }

  getCardSize() {
    const header = this._showHeader() ? 1 : 0;

    // Important: HA may call getCardSize() before hass is injected.
    // If we return 0 here, Lovelace can drop the card entirely from the editor UI.
    if (!this.hass) return header + 1;

    const messages = this._visibleMessages();
    const count = Array.isArray(messages) ? messages.length : 0;

    // When empty (including in editor), reserve at least one row for the empty state.
    return header + (count > 0 ? count : 1);
  }

  /**
   * Sections (grid) view support.
   * Home Assistant uses this to determine the default/min size and to enable the UI "Layout" tab resizing.
   * Each section is 12 columns wide.
   */
  getGridOptions() {
    // Provide only column sizing. Avoid returning `rows` here so Sections can auto-size height
    // based on content (prevents fixed-height behavior and overlap issues when expanding).
    return {
      columns: 12,
      min_columns: 1,
      max_columns: 12,
      // In edit mode + empty state, HA Sections can collapse cards to 0 height unless a min is provided.
      // This keeps the card selectable/movable even when there is no data.
      min_rows: 1,
    };
  }

  _messages() {
    if (!this.hass || !this.config) return [];
    const stateObj = this.hass.states?.[this.config.entity];
    return stateObj ? stateObj.attributes?.messages || [] : [];
  }

  _visibleMessages() {
    const messages = this._messages();
    if (!Array.isArray(messages)) return [];
    const cfg = this.config || {};
    const filterSev = (cfg.filter_severities || []).map((s) => String(s).toUpperCase());
    const filterAreas = (cfg.filter_areas || []).map((s) => String(s).toLowerCase());

    const filtered = messages.filter((m) => {
      const code = String(m.code || '').toUpperCase();
      const area = String(m.area || '').toLowerCase();
      const sevOk = filterSev.length === 0 || filterSev.includes(code);
      const areaOk = filterAreas.length === 0 || filterAreas.some((x) => area.includes(x));
      return sevOk && areaOk;
    });

    const sorted = [...filtered].sort((a, b) => {
      const order = cfg.sort_order || 'severity_then_time';
      if (order === 'time_desc') {
        const at = new Date(a.start || a.published || 0).getTime();
        const bt = new Date(b.start || b.published || 0).getTime();
        return bt - at;
      }
      // severity_then_time
      const as = this._severityRank(a);
      const bs = this._severityRank(b);
      if (as !== bs) return bs - as; // higher first
      const at = new Date(a.start || a.published || 0).getTime();
      const bt = new Date(b.start || b.published || 0).getTime();
      return bt - at;
    });

    const max = Number(cfg.max_items || 0);
    return max > 0 ? sorted.slice(0, max) : sorted;
  }

  _severityRank(item) {
    const code = String(item?.code || '').toUpperCase();
    switch (code) {
      case 'RED':
        return 4;
      case 'ORANGE':
        return 3;
      case 'YELLOW':
        return 2;
      case 'MESSAGE':
        return 1;
      default:
        return 0;
    }
  }

  _handleIconError(e, fallbackPath) {
    const img = e.target;
    if (img && img.src !== fallbackPath) {
      img.src = fallbackPath;
    }
  }

  _iconTemplate(item) {
    if (item.code === 'MESSAGE') {
      const event = item.event.trim().toLowerCase();
      if (event === 'brandrisk' || event === 'fire risk') {
        return html`<img class="icon" src="${fireIcon}" alt="fire risk" @error=${(e) => this._handleIconError(e, '/local/fire.svg')} />`;
      } else if (event === 'risk för vattenbrist' || event === 'risk for water shortage') {
        return html`<img class="icon" src="${waterShortageIcon}" alt="water shortage" @error=${(e) => this._handleIconError(e, '/local/waterShortage.svg')} />`;
      } else if (event === 'höga temperaturer' || event === 'high temperatures') {
        return html`<img class="icon" src="${temperatureIcon}" alt="high temperatures" @error=${(e) => this._handleIconError(e, '/local/temperature.svg')} />`;
      }
      return html`<ha-icon class="icon" icon="mdi:message-alert-outline" aria-hidden="true"></ha-icon>`;
    }
    switch (item.code) {
      case 'YELLOW':
        return html`<img class="icon" src="${yellowWarningIcon}" alt="yellow warning" @error=${(e) => this._handleIconError(e, '/local/yellowWarning.svg')} />`;
      case 'ORANGE':
        return html`<img class="icon" src="${orangeWarningIcon}" alt="orange warning" @error=${(e) => this._handleIconError(e, '/local/orangeWarning.svg')} />`;
      case 'RED':
        return html`<img class="icon" src="${redWarningIcon}" alt="red warning" @error=${(e) => this._handleIconError(e, '/local/redWarning.svg')} />`;
      default:
        return html`<ha-icon class="icon" icon="mdi:alert-circle-outline" aria-hidden="true"></ha-icon>`;
    }
  }

  render() {
    if (!this.hass || !this.config) return html``;
    const stateObj = this.hass.states?.[this.config.entity];
    const t = this._t.bind(this);
    const messages = this._visibleMessages();

    const header = this._showHeader()
      ? (this.config.title || stateObj?.attributes?.friendly_name || 'SMHI')
      : undefined;

    return html`
      <ha-card .header=${header}>
        ${messages.length === 0
          ? html`<div class="empty">${t('no_alerts')}</div>`
          : html`<div class="alerts">${this._renderGrouped(messages)}</div>`}
        ${this._renderEditorMetaControls?.() || html``}
      </ha-card>
    `;
  }

  _renderGrouped(messages) {
    const groupBy = this.config?.group_by || 'none';
    if (groupBy === 'none') {
      return messages.map((item, idx) => this._renderAlert(item, idx));
    }
    const groups = {};
    const getKey = (m) => {
      if (groupBy === 'area') return m.area || '—';
      if (groupBy === 'type') return m.event || '—';
      if (groupBy === 'level') return m.level || '—';
      if (groupBy === 'severity') return (m.code || '—');
      return '—';
    };
    for (const m of messages) {
      const key = getKey(m);
      if (!groups[key]) groups[key] = [];
      groups[key].push(m);
    }
    let keys = Object.keys(groups);
    if (groupBy === 'severity') {
      keys.sort((a, b) => {
        const ra = this._severityRank({ code: String(a).toUpperCase() });
        const rb = this._severityRank({ code: String(b).toUpperCase() });
        return rb - ra;
      });
    } else {
      keys.sort((a, b) => String(a).localeCompare(String(b)));
    }
    return keys.map((key) => html`
      <div class="area-group">
        <div class="meta" style="margin: 0;">${key}</div>
        ${groups[key].map((item, idx) => this._renderAlert(item, idx))}
      </div>
    `);
  }

  _splitMetaOrder(rawOrder) {
    const defaultOrder = ['area', 'type', 'level', 'severity', 'published', 'period', 'divider', 'text', 'map'];
    const base = Array.isArray(rawOrder) && rawOrder.length ? rawOrder : defaultOrder;
    // Deduplicate while preserving first occurrence
    let order = base.map((k) => String(k)).filter((k, i, arr) => arr.indexOf(k) === i);
    // Ensure required special keys exist
    if (!order.includes('divider')) order = [...order, 'divider'];
    if (!order.includes('text')) order = [...order, 'text'];
    if (!order.includes('map')) order = [...order, 'map'];
    const dividerIndex = order.indexOf('divider');
    const inlineKeys = dividerIndex >= 0 ? order.slice(0, dividerIndex) : order.filter((k) => k !== 'divider');
    const detailsKeys = dividerIndex >= 0 ? order.slice(dividerIndex + 1) : [];
    return { order, inlineKeys, detailsKeys };
  }

  _renderAlert(item, idx) {
    const t = this._t.bind(this);
    const code = String(item.code || '').toUpperCase();
    const sevClass =
      code === 'RED' ? 'sev-red' : code === 'ORANGE' ? 'sev-orange' : code === 'YELLOW' ? 'sev-yellow' : 'sev-message';
    const sevBgClass = this.config?.severity_background ? 'bg-severity' : '';
    const showIcon = this.config.show_icon !== false;
    const { inlineKeys, detailsKeys } = this._splitMetaOrder(this.config?.meta_order);

    // Default expansion: keep details collapsed unless user expands
    const alertKey = this._alertKey(item, idx);
    const hasStored = Object.prototype.hasOwnProperty.call(this._expanded || {}, alertKey);
    const expanded = hasStored ? !!this._expanded[alertKey] : false;

    const mkTextBlock = () => {
      if (this.config.show_text === false) return null;
      const txt = this._detailsText(item);
      if (!txt) return null;
      return this._formatDetailsText(txt);
    };

    const mkMapBlock = () => {
      if (!this.config?.show_map) return null;
      if (!item?.geometry) return null;
      const mapId = `smhi-alert-map-${this._sanitizeDomId(alertKey)}`;
      const statusId = `smhi-alert-map-status-${this._sanitizeDomId(alertKey)}`;
      return html`
        <div
          class="map-wrap"
          @pointerdown=${(e) => e.stopPropagation()}
          @pointerup=${(e) => e.stopPropagation()}
          @click=${(e) => e.stopPropagation()}
        >
          <div id=${statusId} class="map-status show">${t('map_loading')}</div>
          <div
            id=${mapId}
            class="geo-map"
            data-map-key=${alertKey}
          ></div>
        </div>
      `;
    };

    const metaSpanFor = (key) => {
      if (key === 'area') {
        return (this.config.show_area !== false && item.area)
          ? html`<span><b>${t('area')}:</b> ${item.area}</span>`
          : null;
      }
      if (key === 'type') {
        return (this.config.show_type !== false && item.event)
          ? html`<span><b>${t('type')}:</b> ${item.event}</span>`
          : null;
      }
      if (key === 'level') {
        return (this.config.show_level !== false && item.level)
          ? html`<span><b>${t('level')}:</b> ${item.level}</span>`
          : null;
      }
      if (key === 'severity') {
        return (this.config.show_severity !== false && item.severity)
          ? html`<span><b>${t('severity')}:</b> ${item.severity}</span>`
          : null;
      }
      if (key === 'published') {
        return (this.config.show_published !== false && item.published)
          ? html`<span><b>${t('published')}:</b> ${this._fmtTs(item.published)}</span>`
          : null;
      }
      if (key === 'period') {
        return (this.config.show_period !== false && (item.start || item.end))
          ? html`<span><b>${t('period')}:</b> ${this._fmtTs(item.start)} – ${this._fmtEnd(item.end)}</span>`
          : null;
      }
      return null;
    };

    const buildSectionBlocks = (keys, section) => {
      // Build blocks in order, but group consecutive meta spans into <div class="meta">...</div>
      const blocks = [];
      let metaGroup = [];
      const flushMeta = () => {
        if (metaGroup.length > 0) {
          blocks.push(html`<div class="meta">${metaGroup}</div>`);
          metaGroup = [];
        }
      };

      for (const k of keys) {
        if (k === 'divider') continue;
        if (k === 'text') {
          flushMeta();
          const node = mkTextBlock();
          if (node) blocks.push(section === 'inline' ? html`<div class="details">${node}</div>` : node);
          continue;
        }
        if (k === 'map') {
          // In details section, only render map when expanded (unless user moved map before divider)
          if (section === 'details' && !expanded) {
            flushMeta();
            continue;
          }
          flushMeta();
          const node = mkMapBlock();
          if (node) blocks.push(section === 'inline' ? html`<div class="details">${node}</div>` : node);
          continue;
        }
        const span = metaSpanFor(k);
        if (span) metaGroup.push(span);
      }

      flushMeta();
      return blocks;
    };

    const sectionHasPotentialContent = (keys) => {
      for (const k of keys) {
        if (k === 'divider') continue;
        if (k === 'text') {
          if (this.config.show_text !== false && !!this._detailsText(item)) return true;
          continue;
        }
        if (k === 'map') {
          if (this.config?.show_map && !!item?.geometry) return true;
          continue;
        }
        if (metaSpanFor(k)) return true;
      }
      return false;
    };

    const inlineBlocks = buildSectionBlocks(inlineKeys, 'inline');
    const detailsBlocks = buildSectionBlocks(detailsKeys, 'details');
    const expandable = sectionHasPotentialContent(detailsKeys);
    const isCompact = !expanded && inlineBlocks.length === 0;

    return html`
      <div
        class="alert ${sevClass} ${sevBgClass} ${isCompact ? 'compact' : ''}"
        role="button"
        tabindex="0"
        aria-label="${item.area || ''}"
        @pointerdown=${(e) => this._onPointerDown(e)}
        @pointerup=${(e) => this._onPointerUp(e, item)}
        @keydown=${(e) => this._onKeydown(e, item)}
      >
        ${showIcon ? html`<div class="icon-col ${isCompact ? 'compact' : ''}">${this._iconTemplate(item)}</div>` : html``}
        <div class="content ${isCompact ? 'compact' : ''}">
          <div class="title">
            <div class="district ${isCompact ? 'compact' : ''}">${item.descr || item.area || item.event || ''}</div>
            ${expandable ? html`
              <div class="toggle-col ${isCompact ? 'compact' : ''}">
                <div
                  class="details-toggle compact"
                  role="button"
                  tabindex="0"
                  aria-expanded="${expanded}"
                  title="${expanded ? t('hide_details') : t('show_details')}"
                  @click=${(e) => this._toggleDetails(e, item, idx)}
                  @pointerdown=${(e) => e.stopPropagation()}
                  @pointerup=${(e) => e.stopPropagation()}
                  @keydown=${(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      this._toggleDetails(e, item, idx);
                    }
                    e.stopPropagation();
                  }}
                >
                  ${expanded ? t('hide_details') : t('show_details')}
                </div>
              </div>
            ` : html``}
          </div>
          ${inlineBlocks.length > 0 ? html`${inlineBlocks}` : html``}
          ${expandable
            ? html`
                <div class="details">
                  ${expanded ? html`
                    ${detailsBlocks.length > 0 ? html`${detailsBlocks}` : html``}
                  ` : html``}
                </div>
              `
            : html``}
        </div>
      </div>`;
  }

  _detailsText(item) {
    // Prefer details; fall back to descr; ensure string
    const primary = item?.details;
    const fallback = item?.descr;
    const text = (primary && String(primary).trim().length > 0)
      ? String(primary)
      : (fallback && String(fallback).trim().length > 0)
        ? String(fallback)
        : '';
    return text || '';
  }

  _normalizeMultiline(value) {
    if (!value) return '';
    let text = String(value).replace(/\r\n?/g, '\n');
    // Trim leading/trailing empty lines
    text = text.replace(/^\s*\n/, '').replace(/\n\s*$/, '');
    const lines = text.split('\n');
    // Determine common leading indent among non-empty lines, preferring positive indents.
    // This avoids the first unindented heading line forcing minIndent to 0
    const indents = lines
      .filter((ln) => ln.trim().length > 0)
      .map((ln) => {
        const m = ln.match(/^(\s*)/);
        return m ? m[1].length : 0;
      });
    const positive = indents.filter((n) => n > 0);
    const minIndent = positive.length > 0 ? Math.min(...positive) : (indents.length > 0 ? Math.min(...indents) : 0);
    const deindented = lines.map((ln) => (minIndent > 0 && ln.startsWith(' '.repeat(minIndent)) ? ln.slice(minIndent) : ln));
    return deindented.join('\n');
  }

  _formatDetailsText(raw) {
    const normalized = this._normalizeMultiline(raw);
    if (!normalized) return null;
    const sections = this._parseDetailsSections(normalized);
    const hasHeadings = sections.some((section) => !!section.heading);
    const hasBlankLines = /\n\s*\n/.test(normalized);
    if (!hasHeadings && !hasBlankLines) {
      return html`<div class="md-text">${normalized}</div>`;
    }

    const blocks = sections
      .map((section) => {
        const paragraphs = this._splitParagraphs(section.lines || []);
        if (paragraphs.length === 0 && !section.heading) return null;
        const wantsList = this._headingWantsList(section.heading, paragraphs);
        const body = wantsList
          ? html`<ul class="details-list">${paragraphs.map((p) => html`<li>${p}</li>`)}</ul>`
          : html`${paragraphs.map((p) => html`<p class="details-paragraph">${p}</p>`)}`;
        return html`
          <div class="details-section">
            ${section.heading ? html`<div class="details-heading">${section.heading}</div>` : html``}
            ${body}
          </div>
        `;
      })
      .filter(Boolean);

    return html`<div class="details-text">${blocks}</div>`;
  }

  _parseDetailsSections(text) {
    const lines = String(text).split('\n');
    const sections = [];
    let current = null;

    const pushCurrent = () => {
      if (!current) return;
      const trimmed = this._trimEmptyLines(current.lines || []);
      if (trimmed.length === 0 && !current.heading) {
        current = null;
        return;
      }
      sections.push({ heading: current.heading, lines: trimmed });
      current = null;
    };

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        if (current) current.lines.push('');
        continue;
      }
      const headingMatch = this._matchDetailsHeading(line);
      if (headingMatch) {
        pushCurrent();
        current = { heading: headingMatch.heading, lines: [] };
        if (headingMatch.rest) current.lines.push(headingMatch.rest);
        continue;
      }
      if (!current) current = { heading: null, lines: [] };
      current.lines.push(line);
    }
    pushCurrent();
    return sections;
  }

  _matchDetailsHeading(line) {
    const match = String(line).match(/^([^:]{2,80})\s*:\s*(.*)$/);
    if (!match) return null;
    const heading = match[1].trim();
    if (!heading) return null;
    const rest = (match[2] || '').trim();
    const words = heading.split(/\s+/).filter(Boolean);
    if (heading.length > 50 || words.length > 6) return null;
    if (!/[A-Za-zÅÄÖåäö]/.test(heading)) return null;
    if (/[0-9]/.test(heading) && !heading.includes('?')) return null;
    if (/https?:\/\//i.test(heading)) return null;
    return { heading, rest };
  }

  _trimEmptyLines(lines) {
    let start = 0;
    while (start < lines.length && !lines[start].trim()) start += 1;
    let end = lines.length - 1;
    while (end >= start && !lines[end].trim()) end -= 1;
    return lines.slice(start, end + 1);
  }

  _splitParagraphs(lines) {
    const paragraphs = [];
    let current = [];
    const flush = () => {
      if (current.length === 0) return;
      paragraphs.push(current.join(' ').replace(/\s+/g, ' ').trim());
      current = [];
    };

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        flush();
        continue;
      }
      current.push(trimmed);
    }
    flush();
    return paragraphs;
  }

  _headingWantsList(heading, paragraphs) {
    if (!heading) return false;
    if (!Array.isArray(paragraphs) || paragraphs.length < 2) return false;
    const normalized = heading.trim().toLowerCase();
    return normalized.includes('tänka')
      || normalized.includes('att tänka')
      || normalized.includes('tips')
      || normalized.includes('advice')
      || normalized.includes('recommendation')
      || normalized.includes('what should i');
  }

  _toggleDetails(e, item, idx) {
    e.stopPropagation();
    const key = this._alertKey(item, idx);
    this._expanded = { ...this._expanded, [key]: !this._expanded[key] };
  }

  _onPointerDown(e) {
    if (e.button !== 0) return; // left click only
    clearTimeout(this._holdTimer);
    this._holdFired = false;
    this._holdTimer = setTimeout(() => {
      this._holdFired = true;
      // we don't know item here; handled on pointerup
    }, 500);
  }

  _onPointerUp(e, item) {
    if (e.button !== 0) return;
    clearTimeout(this._holdTimer);
    if (this._holdFired) {
      this._runAction(this.config?.hold_action || this.config?.tap_action || { action: 'more-info' }, item);
      return;
    }
    const now = Date.now();
    if (this._lastTap && now - this._lastTap < 250) {
      this._lastTap = 0;
      this._runAction(this.config?.double_tap_action || this.config?.tap_action || { action: 'more-info' }, item);
    } else {
      this._lastTap = now;
      clearTimeout(this._tapTimer);
      this._tapTimer = setTimeout(() => {
        // if no double tap happened
        if (this._lastTap && Date.now() - this._lastTap >= 250) {
          this._lastTap = 0;
          this._runAction(this.config?.tap_action || { action: 'more-info' }, item);
        }
      }, 260);
    }
  }

  _onKeydown(e, item) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      this._runAction(this.config?.tap_action || { action: 'more-info' }, item);
    }
  }

  _alertKey(item, idx) {
    return `${String(item.code || '')}-${String(item.area || '')}-${String(item.start || item.published || idx)}`;
  }

  _fmtTs(value) {
    return this._formatDate(value);
  }

  _fmtEnd(end) {
    const val = String(end || '').trim().toLowerCase();
    if (!end || val === 'okänt' || val === 'unknown') return this._t('unknown');
    return this._formatDate(end);
  }

  _formatDate(value) {
    if (!value) return '';
    const date = this._parseDate(value);
    if (!date) return String(value);
    const locale = (this.hass?.language || 'en').toLowerCase();
    const format = this.config?.date_format || 'locale';
    if (format === 'weekday_time') {
      return this._formatDateParts(
        date,
        locale,
        { weekday: 'long' },
        { hour: '2-digit', minute: '2-digit' },
      );
    }
    if (format === 'day_month_time') {
      return this._formatDateParts(
        date,
        locale,
        { day: 'numeric', month: 'long' },
        { hour: '2-digit', minute: '2-digit' },
      );
    }
    if (format === 'day_month_time_year') {
      return this._formatDateParts(
        date,
        locale,
        { day: 'numeric', month: 'long', year: 'numeric' },
        { hour: '2-digit', minute: '2-digit' },
      );
    }
    return date.toLocaleString(locale);
  }

  _formatDateParts(date, locale, dateOptions, timeOptions) {
    const safeTimeOptions = timeOptions ? { ...timeOptions } : null;
    if (safeTimeOptions && !Object.prototype.hasOwnProperty.call(safeTimeOptions, 'hour12')) {
      safeTimeOptions.hour12 = false;
    }
    const dateStr = dateOptions
      ? new Intl.DateTimeFormat(locale, dateOptions).format(date)
      : '';
    const timeStr = safeTimeOptions
      ? new Intl.DateTimeFormat(locale, safeTimeOptions).format(date)
      : '';
    if (dateStr && timeStr) return `${dateStr} ${timeStr}`;
    return dateStr || timeStr || '';
  }

  _parseDate(value) {
    if (!value) return null;
    if (value instanceof Date) {
      return Number.isNaN(value.getTime()) ? null : value;
    }
    if (typeof value === 'number') {
      const numericDate = new Date(value);
      return Number.isNaN(numericDate.getTime()) ? null : numericDate;
    }
    const raw = String(value).trim();
    if (!raw) return null;
    let normalized = raw;
    if (/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/.test(raw)) {
      normalized = raw.replace(' ', 'T');
    }
    const parsed = new Date(normalized);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  _showHeader() {
    return this.config?.show_header !== false;
  }

  updated() {
    // When geometry maps are enabled, create/update maps for alerts where the map is actually rendered.
    this._maybeInitMaps();
  }

  _maybeInitMaps() {
    if (!this.config?.show_map) return;
    if (!this.renderRoot) return;

    const messages = this._visibleMessages();
    const { inlineKeys, detailsKeys } = this._splitMetaOrder(this.config?.meta_order);
    const mapInInline = inlineKeys.includes('map');
    const mapInDetails = detailsKeys.includes('map');
    const activeKeys = new Set();
    for (let i = 0; i < messages.length; i++) {
      const item = messages[i];
      const key = this._alertKey(item, i);
      const expanded = !!this._expanded?.[key];
      const mapVisible = (mapInInline || (mapInDetails && expanded));
      if (!mapVisible) continue;
      if (!item?.geometry) continue;
      const mapId = `smhi-alert-map-${this._sanitizeDomId(key)}`;
      const el = this.renderRoot.querySelector(`#${mapId}`);
      if (!el) continue;
      activeKeys.add(key);
      this._ensureLeafletAndRenderMap(key, el, item.geometry, String(item.code || '').toUpperCase()).catch(() => {
        const statusEl = this.renderRoot?.querySelector?.(`#smhi-alert-map-status-${this._sanitizeDomId(key)}`);
        if (statusEl) {
          statusEl.textContent = this._t('map_failed');
          statusEl.classList.add('show');
        }
      });
    }

    // Cleanup maps that are no longer rendered (collapsed/filtered away)
    for (const [key, entry] of this._maps.entries()) {
      if (activeKeys.has(key)) continue;
      try {
        entry?.map?.remove?.();
      } catch (e) {}
      this._maps.delete(key);
    }
  }

  _sanitizeDomId(value) {
    // Important: this value is used inside querySelector(`#${id}`).
    // Characters like ':' and '.' make the selector invalid unless escaped, so we strip them here.
    // We already prefix with 'smhi-alert-map-' / 'smhi-alert-map-status-' so the final id starts with a letter.
    return String(value || '').replace(/[^a-zA-Z0-9\-_]/g, '_');
  }

  _severityStyle(code) {
    const c = String(code || '').toUpperCase();
    const accentVar =
      c === 'RED' ? 'var(--smhi-alert-red, var(--error-color, #e74c3c))'
      : c === 'ORANGE' ? 'var(--smhi-alert-orange, #e67e22)'
      : c === 'YELLOW' ? 'var(--smhi-alert-yellow, #f1c40f)'
      : 'var(--smhi-alert-message, var(--primary-color))';
    return {
      color: accentVar,
      fillColor: accentVar,
      weight: 2,
      opacity: 0.9,
      fillOpacity: 0.18,
    };
  }

  _geoSignature(geometry) {
    try {
      if (!geometry || typeof geometry !== 'object') return '';
      const t = geometry.type || '';
      if (t === 'FeatureCollection') return `FC:${(geometry.features || []).length}`;
      if (t === 'Feature') return `F:${geometry.geometry?.type || ''}`;
      if (Array.isArray(geometry.coordinates)) return `${t}:${geometry.coordinates.length}`;
      return String(t);
    } catch (e) {
      return '';
    }
  }

  async _ensureLeafletAndRenderMap(key, containerEl, geometry, code) {
    this._ensureLeafletCssInShadowRoot();
    const statusEl = this.renderRoot?.querySelector?.(`#smhi-alert-map-status-${this._sanitizeDomId(key)}`);
    if (statusEl) {
      statusEl.textContent = this._t('map_loading_leaflet');
      statusEl.classList.add('show');
    }
    const L = await this._ensureLeaflet();
    if (!L) return;

    const sig = `${this._geoSignature(geometry)}|${String(code || '').toUpperCase()}`;
    const existing = this._maps.get(key);
    const containerChanged = existing?.container && existing.container !== containerEl;

    if (existing && containerChanged) {
      try { existing.map.remove(); } catch (e) {}
      this._maps.delete(key);
    }

    let entry = this._maps.get(key);
    if (!entry) {
      const map = L.map(containerEl, {
        zoomControl: this.config?.map_zoom_controls !== false,
        attributionControl: false,
        // Keep wheel zoom off by default so dashboard scroll isn't affected
        scrollWheelZoom: this.config?.map_scroll_wheel === true,
        // Double click zoom is a nice zoom affordance without interfering with page scroll
        doubleClickZoom: true,
        boxZoom: false,
        keyboard: false,
        touchZoom: true,
        tap: false,
      });
      const tile = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '&copy; OpenStreetMap contributors',
      }).addTo(map);
      entry = { map, layer: null, sig: '', container: containerEl };
      this._maps.set(key, entry);
    }

    if (entry.sig !== sig) {
      if (statusEl) {
        statusEl.textContent = this._t('map_rendering');
        statusEl.classList.add('show');
      }
      try { entry.layer?.remove?.(); } catch (e) {}
      entry.layer = L.geoJSON(geometry, { style: () => this._severityStyle(code) }).addTo(entry.map);
      entry.sig = sig;
      try {
        const bounds = entry.layer.getBounds?.();
        if (bounds && bounds.isValid && bounds.isValid()) {
          entry.map.fitBounds(bounds, { padding: [12, 12] });
        }
      } catch (e) {}
    }

    // When a map is created in a newly rendered/expanded container, Leaflet needs a size invalidate.
    requestAnimationFrame(() => {
      try { entry.map.invalidateSize(); } catch (e) {}
    });

    // Hide loading overlay once we have a map instance.
    if (statusEl) {
      statusEl.classList.remove('show');
      statusEl.textContent = '';
    }
  }

  _ensureLeaflet() {
    // Share one loader promise across all card instances.
    window.__smhiAlertLeafletPromise = window.__smhiAlertLeafletPromise || null;
    if (window.L && window.L.map) return Promise.resolve(window.L);
    if (window.__smhiAlertLeafletPromise) return window.__smhiAlertLeafletPromise;

    // Prefer ESM import (typically CSP-friendlier in HA than injecting <script src=...>).
    window.__smhiAlertLeafletPromise = (async () => {
      try {
        const mod = await this._withTimeout(import(LEAFLET_ESM_URL), 12000, 'Leaflet ESM import timed out');
        const L = mod?.default || mod?.L || mod;
        if (L && L.map) {
          // Also set window.L for any downstream libs expecting the global.
          window.L = window.L || L;
          return L;
        }
        throw new Error('Leaflet ESM loaded but did not expose L.map');
      } catch (err) {
        // Fallback to classic script tag (may still be blocked by CSP).
        const jsId = 'smhi-alert-leaflet-js';
        return await new Promise((resolve, reject) => {
          try {
            if (window.L && window.L.map) {
              resolve(window.L);
              return;
            }
            let script = document.getElementById(jsId);
            if (!script) {
              script = document.createElement('script');
              script.id = jsId;
              script.src = LEAFLET_JS_SRC;
              script.async = true;
              document.head.appendChild(script);
            }
            script.addEventListener('load', () => resolve(window.L));
            script.addEventListener('error', () => reject(err || new Error('Failed to load Leaflet')));
          } catch (e) {
            reject(err || e);
          }
        });
      }
    })();

    return window.__smhiAlertLeafletPromise;
  }

  _withTimeout(promise, ms, message) {
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error(message || 'Timed out')), ms);
      promise.then((v) => { clearTimeout(t); resolve(v); }).catch((e) => { clearTimeout(t); reject(e); });
    });
  }

  _ensureLeafletCssInShadowRoot() {
    const id = 'smhi-alert-leaflet-css-shadow';
    try {
      if (!this.renderRoot) return;
      if (this.renderRoot.querySelector(`#${id}`)) return;
      const link = document.createElement('link');
      link.id = id;
      link.rel = 'stylesheet';
      link.href = LEAFLET_CSS_HREF;
      this.renderRoot.appendChild(link);
    } catch (e) {
      // ignore
    }
  }

  shouldUpdate(changed) {
    if (changed.has('config')) return true;
    if (changed.has('hass')) {
      const stateObj = this.hass.states?.[this.config.entity];
      const lastUpdate = String(stateObj?.attributes?.last_update || '');
      const messages = stateObj?.attributes?.messages || [];
      // Include details/descr to re-render when description text changes
      const msgKey = JSON.stringify(messages?.map((m) => [m.code, m.area, m.start, m.published, m.details, m.descr]));
      const combinedKey = `${lastUpdate}|${msgKey}`;
      if (this._lastKey !== combinedKey) {
        this._lastKey = combinedKey;
        return true;
      }
      return false;
    }
    return true;
  }

  _t(key) {
    const lang = (this.hass?.language || 'en').toLowerCase();
    const dict = {
      en: {
        no_alerts: 'No alerts',
        area: 'Area',
        type: 'Type',
        level: 'Level',
        severity: 'Severity',
        published: 'Published',
        period: 'Period',
        // description_short kept for backward compat but unused
        description_short: 'Descr',
        show_details: 'Show details',
        hide_details: 'Hide details',
        unknown: 'Unknown',
        map_loading: 'Loading map…',
        map_loading_leaflet: 'Loading map (Leaflet)…',
        map_rendering: 'Rendering area…',
        map_failed: 'Map failed to load (blocked by browser/HA CSP)',
      },
      sv: {
        no_alerts: 'Inga varningar',
        area: 'Område',
        type: 'Typ',
        level: 'Nivå',
        severity: 'Allvarlighetsgrad',
        published: 'Publicerad',
        period: 'Period',
        // description_short kept for backward compat but unused
        description_short: 'Beskrivning',
        show_details: 'Visa detaljer',
        hide_details: 'Dölj detaljer',
        unknown: 'Okänt',
        map_loading: 'Laddar karta…',
        map_loading_leaflet: 'Laddar karta (Leaflet)…',
        map_rendering: 'Ritar område…',
        map_failed: 'Kartan kunde inte laddas (blockerad av webbläsare/HA CSP)',
      },
    };
    return (dict[lang] || dict.en)[key] || key;
  }

  _normalizeConfig(config) {
    const normalized = { ...config };
    // Backwards compatibility mappings
    if (normalized.show_text === undefined && normalized.show_details !== undefined) {
      normalized.show_text = normalized.show_details;
    }
    // Defaults
    if (normalized.show_header === undefined) normalized.show_header = true;
    if (normalized.show_area === undefined) normalized.show_area = true;
    if (normalized.show_type === undefined) normalized.show_type = true;
    if (normalized.show_level === undefined) normalized.show_level = true;
    if (normalized.show_severity === undefined) normalized.show_severity = true;
    if (normalized.show_published === undefined) normalized.show_published = true;
    if (normalized.show_period === undefined) normalized.show_period = true;
    if (normalized.show_text === undefined) normalized.show_text = true;
    if (normalized.show_icon === undefined) normalized.show_icon = true;
    if (normalized.severity_background === undefined) normalized.severity_background = false;
    if (normalized.show_map === undefined) normalized.show_map = false;
    if (normalized.map_zoom_controls === undefined) normalized.map_zoom_controls = true;
    if (normalized.map_scroll_wheel === undefined) normalized.map_scroll_wheel = false;
    if (normalized.max_items === undefined) normalized.max_items = 0;
    if (normalized.sort_order === undefined) normalized.sort_order = 'severity_then_time';
    if (normalized.date_format === undefined) normalized.date_format = 'locale';
    if (normalized.group_by === undefined) normalized.group_by = 'none';
    const allowedDateFormats = ['locale', 'day_month_time', 'weekday_time', 'day_month_time_year'];
    if (!allowedDateFormats.includes(normalized.date_format)) {
      normalized.date_format = 'locale';
    }
    if (!Array.isArray(normalized.meta_order) || normalized.meta_order.length === 0) {
      // Default to placing text + map in the details section (after divider)
      normalized.meta_order = ['area','type','level','severity','published','period','divider','text','map'];
    } else {
      // Ensure divider/text/map exist
      if (!normalized.meta_order.includes('divider')) normalized.meta_order = [...normalized.meta_order, 'divider'];
      if (!normalized.meta_order.includes('text')) normalized.meta_order = [...normalized.meta_order, 'text'];
      if (!normalized.meta_order.includes('map')) normalized.meta_order = [...normalized.meta_order, 'map'];
    }
    if (!Array.isArray(normalized.filter_severities)) normalized.filter_severities = [];
    if (!Array.isArray(normalized.filter_areas)) normalized.filter_areas = [];
    // collapse_details is no longer used; collapse is inferred by divider position
    delete normalized.collapse_details;
    if (Object.prototype.hasOwnProperty.call(normalized, 'hide_when_empty')) delete normalized.hide_when_empty;
    if (Object.prototype.hasOwnProperty.call(normalized, 'debug')) delete normalized.debug; // legacy
    // `map_height` is deprecated (map is now responsive). Ignore saved configs that still include it.
    if (Object.prototype.hasOwnProperty.call(normalized, 'map_height')) delete normalized.map_height;
    if (Object.prototype.hasOwnProperty.call(normalized, 'map_zoom')) delete normalized.map_zoom; // legacy
    if (normalized.show_border === undefined) normalized.show_border = true; // kept for compat but unused
    return normalized;
  }

  static getConfigElement() {
    return document.createElement('smhi-alert-card-editor');
  }

  static getStubConfig(hass, entities) {
    return {
      entity: entities.find((e) => e.startsWith('sensor.')) || '',
      title: '',
      show_header: true,
      show_icon: true,
      severity_background: false,
      show_map: false,
      map_zoom_controls: true,
      map_scroll_wheel: false,
      show_area: true,
      show_type: true,
      show_level: true,
      show_severity: true,
      show_published: true,
      show_period: true,
      show_text: true,
      max_items: 0,
      sort_order: 'severity_then_time',
      date_format: 'locale',
      group_by: 'none',
      filter_severities: [],
      filter_areas: [],
      // collapse inferred by divider; default puts text in details (after divider)
      meta_order: ['area','type','level','severity','published','period','divider','text','map'],
    };
  }
}

if (!customElements.get('smhi-alert-card')) {
  customElements.define('smhi-alert-card', SmhiAlertCard);
}

class SmhiAlertCardEditor extends LitElement {
  static properties = {
    hass: {},
    _config: {},
  };

  static styles = css`
    .container { padding: 8px 0 0 0; }
    .map-hint { margin: 10px 0 12px 0; padding: 0 12px; }
    .map-hint .hint-title { font-weight: 600; margin-bottom: 4px; }
    .map-hint .hint-text { color: var(--secondary-text-color); font-size: 0.95em; line-height: 1.4; }
    .meta-fields { margin: 12px 0; padding: 8px 12px; }
    .meta-fields-title { color: var(--secondary-text-color); margin-bottom: 6px; }
    .meta-row { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 8px; padding: 6px 0; }
    .order-actions { display: flex; gap: 6px; }
  `;

  setConfig(config) {
    this._config = config;
  }

  render() {
    if (!this.hass || !this._config) return html``;
    const lang = (this.hass?.language || 'en').toLowerCase();
    const dateFormatOptions = lang.startsWith('sv')
      ? [
          { value: 'locale', label: 'Systemstandard' },
          { value: 'day_month_time', label: '14 januari 13:00' },
          { value: 'weekday_time', label: 'Onsdag 13:00' },
          { value: 'day_month_time_year', label: '14 januari 2026 13:00' },
        ]
      : [
          { value: 'locale', label: 'System default' },
          { value: 'day_month_time', label: '14 January 13:00' },
          { value: 'weekday_time', label: 'Wednesday 13:00' },
          { value: 'day_month_time_year', label: '14 January 2026 13:00' },
        ];
    const dateFormatLabel = lang.startsWith('sv') ? 'Datumformat' : 'Date format';
    const schema = [
      { name: 'entity', label: 'Entity', required: true, selector: { entity: { domain: 'sensor' } } },
      { name: 'title', label: 'Title', selector: { text: {} } },
      { name: 'show_header', label: 'Show header', selector: { boolean: {} } },
      { name: 'show_icon', label: 'Show icon', selector: { boolean: {} } },
      { name: 'severity_background', label: 'Severity background', selector: { boolean: {} } },
      { name: 'show_map', label: 'Show map (geometry)', selector: { boolean: {} } },
      { name: 'map_zoom_controls', label: 'Map zoom controls (+/−)', selector: { boolean: {} } },
      { name: 'map_scroll_wheel', label: 'Map scroll wheel zoom', selector: { boolean: {} } },
      { name: 'max_items', label: 'Max items', selector: { number: { min: 0, mode: 'box' } } },
      {
        name: 'sort_order', label: 'Sort order',
        selector: { select: { mode: 'dropdown', options: [
          { value: 'severity_then_time', label: 'Severity then time' },
          { value: 'time_desc', label: 'Time (newest first)' },
        ] } },
      },
      { name: 'date_format', label: dateFormatLabel, selector: { select: { mode: 'dropdown', options: dateFormatOptions } } },
      { name: 'group_by', label: 'Group by', selector: { select: { mode: 'dropdown', options: [
        { value: 'none', label: 'No grouping' },
        { value: 'area', label: 'By area' },
        { value: 'type', label: 'By type' },
        { value: 'level', label: 'By level' },
        { value: 'severity', label: 'By severity' },
      ] } } },
      { name: 'filter_severities', label: 'Filter severities', selector: { select: { multiple: true, options: [
        { value: 'RED', label: 'RED' },
        { value: 'ORANGE', label: 'ORANGE' },
        { value: 'YELLOW', label: 'YELLOW' },
        { value: 'MESSAGE', label: 'MESSAGE' },
      ] } } },
      { name: 'filter_areas', label: 'Filter areas (comma-separated)', selector: { text: {} } },
      // No explicit collapse or show_text; details are inferred by divider & per-meta toggles
      // actions (use ui_action selector for full UI in editor)
      { name: 'tap_action', label: 'Tap action', selector: { ui_action: {} } },
      { name: 'double_tap_action', label: 'Double tap action', selector: { ui_action: {} } },
      { name: 'hold_action', label: 'Hold action', selector: { ui_action: {} } },
    ];

    const data = {
      entity: this._config.entity || '',
      title: this._config.title || '',
      show_header: this._config.show_header !== undefined ? this._config.show_header : true,
      show_icon: this._config.show_icon !== undefined ? this._config.show_icon : true,
      severity_background: this._config.severity_background !== undefined ? this._config.severity_background : false,
      show_map: this._config.show_map !== undefined ? this._config.show_map : false,
      map_zoom_controls: this._config.map_zoom_controls !== undefined ? this._config.map_zoom_controls : true,
      map_scroll_wheel: this._config.map_scroll_wheel !== undefined ? this._config.map_scroll_wheel : false,
      max_items: this._config.max_items ?? 0,
      sort_order: this._config.sort_order || 'severity_then_time',
      date_format: this._config.date_format || 'locale',
      group_by: this._config.group_by || 'none',
      filter_severities: this._config.filter_severities || [],
      filter_areas: (this._config.filter_areas || []).join(', '),
      // collapse inferred by divider
      show_area: this._config.show_area !== undefined ? this._config.show_area : true,
      show_type: this._config.show_type !== undefined ? this._config.show_type : true,
      show_level: this._config.show_level !== undefined ? this._config.show_level : true,
      show_severity: this._config.show_severity !== undefined ? this._config.show_severity : true,
      show_published: this._config.show_published !== undefined ? this._config.show_published : true,
      show_period: this._config.show_period !== undefined ? this._config.show_period : true,
      show_text: this._config.show_text !== undefined ? this._config.show_text : (this._config.show_details !== undefined ? this._config.show_details : true),
      tap_action: this._config.tap_action || {},
      double_tap_action: this._config.double_tap_action || {},
      hold_action: this._config.hold_action || {},
    };

    const allowed = ['area','type','level','severity','published','period','map'];
    const special = ['divider','text'];
    const allowedWithSpecial = [...allowed, ...special];
    const currentOrderRaw = (this._config.meta_order && Array.isArray(this._config.meta_order) && this._config.meta_order.length)
      ? this._config.meta_order.filter((k) => allowedWithSpecial.includes(k))
      : ['area','type','level','severity','published','period','divider','text','map'];
    // ensure presence
    let currentOrder = [...currentOrderRaw];
    if (!currentOrder.includes('divider')) currentOrder.push('divider');
    if (!currentOrder.includes('text')) currentOrder.push('text');
    if (!currentOrder.includes('map')) currentOrder.push('map');
    const filledOrder = [...currentOrder, ...allowedWithSpecial.filter((k) => !currentOrder.includes(k))];

    const schemaTop = schema.filter((s) => !['tap_action','double_tap_action','hold_action'].includes(s.name));
    const schemaActions = schema.filter((s) => ['tap_action','double_tap_action','hold_action'].includes(s.name));

    const mapHint = {
      title: 'Note: Requires an integration setting',
      text: 'For “Show map (geometry)” to work, enable “Include geometry (map polygons)” in the SMHI Alerts integration (Settings → Devices & Services → SMHI Alerts → Configure).',
    };

    // Keep original schema order, but insert the hint directly below "show_map"
    // by splitting the form at that exact point.
    const showMapIdx = schemaTop.findIndex((s) => s.name === 'show_map');
    const schemaBeforeShowMap = showMapIdx >= 0 ? schemaTop.slice(0, showMapIdx) : schemaTop;
    const schemaShowMapOnly = showMapIdx >= 0 ? schemaTop.slice(showMapIdx, showMapIdx + 1) : [];
    const schemaAfterShowMap = showMapIdx >= 0 ? schemaTop.slice(showMapIdx + 1) : [];

    return html`
      <div class="container">
        <ha-form
          .hass=${this.hass}
          .data=${data}
          .schema=${schemaBeforeShowMap}
          .computeLabel=${this._computeLabel}
          @value-changed=${this._valueChanged}
        ></ha-form>
        ${schemaShowMapOnly.length
          ? html`
              <ha-form
                .hass=${this.hass}
                .data=${data}
                .schema=${schemaShowMapOnly}
                .computeLabel=${this._computeLabel}
                @value-changed=${this._valueChanged}
              ></ha-form>
            `
          : html``}
        ${data.show_map
          ? html`
              <div class="map-hint">
                <div class="hint-title">${mapHint.title}</div>
                <div class="hint-text">${mapHint.text}</div>
              </div>
            `
          : html``}
        ${schemaAfterShowMap.length
          ? html`
              <ha-form
                .hass=${this.hass}
                .data=${data}
                .schema=${schemaAfterShowMap}
                .computeLabel=${this._computeLabel}
                @value-changed=${this._valueChanged}
              ></ha-form>
            `
          : html``}
        <div class="meta-fields">
          ${filledOrder.map((key, index) => {
            if (key === 'divider') {
              return html`
                <ha-settings-row class="meta-divider-row">
                  <span slot="heading">Details divider</span>
                  <div class="order-actions">
                    <mwc-icon-button @click=${() => this._moveMeta(key, -1)} .disabled=${index === 0} aria-label="Move up">
                      <ha-icon icon="mdi:chevron-up"></ha-icon>
                    </mwc-icon-button>
                    <mwc-icon-button @click=${() => this._moveMeta(key, 1)} .disabled=${index === filledOrder.length - 1} aria-label="Move down">
                      <ha-icon icon="mdi:chevron-down"></ha-icon>
                    </mwc-icon-button>
                  </div>
                </ha-settings-row>
              `;
            }
            return html`
              <ha-settings-row class="meta-row">
                <span slot="heading">${this._labelForMeta(key)}</span>
                <span slot="description"></span>
                <div class="order-actions">
                  <mwc-icon-button @click=${() => this._moveMeta(key, -1)} .disabled=${index === 0} aria-label="Move up">
                    <ha-icon icon="mdi:chevron-up"></ha-icon>
                  </mwc-icon-button>
                  <mwc-icon-button @click=${() => this._moveMeta(key, 1)} .disabled=${index === filledOrder.length - 1} aria-label="Move down">
                    <ha-icon icon="mdi:chevron-down"></ha-icon>
                  </mwc-icon-button>
                </div>
                <ha-switch
                  .checked=${this._isMetaShown(key)}
                  @change=${(e) => this._toggleMeta(key, e)}
                ></ha-switch>
              </ha-settings-row>`;
          })}
        </div>
        <ha-form
          .hass=${this.hass}
          .data=${data}
          .schema=${schemaActions}
          .computeLabel=${this._computeLabel}
          @value-changed=${this._valueChanged}
        ></ha-form>
      </div>
    `;
  }

  _valueChanged = (ev) => {
    if (!this._config || !this.hass) return;
    const value = ev.detail?.value || {};
    const next = { ...this._config, ...value };
    // normalize filter_areas from comma-separated string
    if (typeof next.filter_areas === 'string') {
      next.filter_areas = next.filter_areas
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    }
    this._config = next;
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: next } }));
  };

  _isMetaShown(key) {
    if (key === 'area') return this._config.show_area !== false;
    if (key === 'type') return this._config.show_type !== false;
    if (key === 'level') return this._config.show_level !== false;
    if (key === 'severity') return this._config.show_severity !== false;
    if (key === 'published') return this._config.show_published !== false;
    if (key === 'period') return this._config.show_period !== false;
    if (key === 'text') return this._config.show_text !== false;
    if (key === 'map') return this._config.show_map === true;
    if (key === 'divider') return true;
    return true;
  }

  _toggleMeta(key, ev) {
    const on = ev?.target?.checked ?? true;
    let next = { ...this._config };
    if (key === 'area') next.show_area = on;
    else if (key === 'type') next.show_type = on;
    else if (key === 'level') next.show_level = on;
    else if (key === 'severity') next.show_severity = on;
    else if (key === 'published') next.show_published = on;
    else if (key === 'period') next.show_period = on;
    else if (key === 'text') next.show_text = on;
    else if (key === 'map') next.show_map = on;
    this._config = next;
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: next } }));
  }

  _moveMeta(key, delta) {
    // Normalize to the same order the UI renders (includes 'divider' and 'text' and all allowed keys),
    // so moving across the divider is always possible and saved back stably.
    const baseKeys = ['area','type','level','severity','published','period','map'];
    const specialKeys = ['divider','text'];
    const allKeys = [...baseKeys, ...specialKeys];
    const raw = (this._config.meta_order && Array.isArray(this._config.meta_order) && this._config.meta_order.length)
      ? this._config.meta_order.filter((k) => allKeys.includes(k))
      : [...allKeys];
    // Deduplicate while preserving first occurrence
    let current = raw.filter((k, i) => raw.indexOf(k) === i);
    // Ensure presence of divider/text
    if (!current.includes('divider')) current.push('divider');
    if (!current.includes('text')) current.push('text');
    // Ensure all allowed keys are present so their relative order is explicit
    const filled = [...current, ...allKeys.filter((k) => !current.includes(k))];

    const idx = filled.indexOf(key);
    if (idx < 0) return;
    const newIdx = Math.max(0, Math.min(filled.length - 1, idx + delta));
    if (newIdx === idx) return;
    const next = [...filled];
    next.splice(idx, 1);
    next.splice(newIdx, 0, key);
    this._config = { ...this._config, meta_order: next };
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: this._config } }));
  }

  _labelForMeta(key) {
    const map = { area: 'Area', type: 'Type', level: 'Level', severity: 'Severity', published: 'Published', period: 'Period', text: 'Text', map: 'Map', divider: '— Details —' };
    return map[key] || key;
  }

  _computeLabel = (schema) => {
    if (schema.label) return schema.label;
    const labels = {
      entity: 'Entity',
      title: 'Title',
      show_header: 'Show header',
      show_icon: 'Show icon',
      severity_background: 'Severity background',
      show_map: 'Show map (geometry)',
      map_zoom_controls: 'Map zoom controls (+/−)',
      map_scroll_wheel: 'Map scroll wheel zoom',
      max_items: 'Max items',
      sort_order: 'Sort order',
      date_format: 'Date format',
      group_by: 'Group by',
      filter_severities: 'Filter severities',
      filter_areas: 'Filter areas (comma-separated)',
       // collapse_details removed
      show_area: 'Show area',
      show_type: 'Show type',
      show_level: 'Show level',
      show_severity: 'Show severity',
      show_published: 'Show published',
      show_period: 'Show period',
       // show_text is controlled as a meta toggle, not a top-level control
      tap_action: 'Tap action',
      double_tap_action: 'Double tap action',
      hold_action: 'Hold action',
    };
    return labels[schema.name] || schema.name;
  };
}

if (!customElements.get('smhi-alert-card-editor')) {
  customElements.define('smhi-alert-card-editor', SmhiAlertCardEditor);
}

// Register the card so it appears in the "Add card" dialog
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'smhi-alert-card',
  name: 'SMHI Alert Card',
  description: 'Displays SMHI warnings for selected regions using the SMHI Weather Warnings & Alerts integration',
  preview: true,
});

// Actions support
SmhiAlertCard.prototype._onRowAction = function (e, item) {
  // Only trigger card action when clicking outside the toggle link
  const tag = (e.composedPath?.()[0]?.tagName || '').toLowerCase();
  if (tag === 'ha-markdown' || (e.target && e.target.classList && e.target.classList.contains('details-toggle'))) {
    return;
  }
  const action = this.config?.tap_action || { action: 'more-info' };
  this._runAction(action, item);
};

SmhiAlertCard.prototype._runAction = function (action, item) {
  const a = action?.action || 'more-info';
  if (a === 'none') return;
  if (a === 'more-info') {
    const ev = new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId: this.config.entity } });
    this.dispatchEvent(ev);
    return;
  }
  if (a === 'navigate' && action.navigation_path) {
    history.pushState(null, '', action.navigation_path);
    const ev = new Event('location-changed', { bubbles: true, composed: true });
    this.dispatchEvent(ev);
    return;
  }
  if (a === 'url' && action.url_path) {
    window.open(action.url_path, '_blank');
    return;
  }
  if (a === 'call-service' && action.service) {
    const [domain, service] = action.service.split('.');
    this.hass.callService(domain, service, action.service_data || {});
    return;
  }
};
