// ExtendScript side of the Text Probe. ES3: no JSON object, so results are built by hand
// and parsed by index.html. Every value is passed through tp_q.

function tp_q(s) {
	s = String(s);
	var out = '"';
	for (var i = 0; i < s.length; i++) {
		var ch = s.charAt(i), c = s.charCodeAt(i);
		if (ch == '"' || ch == '\\') out += '\\' + ch;
		else if (c < 32 || c > 126) out += '\\u' + ('0000' + c.toString(16)).slice(-4);
		else out += ch;
	}
	return out + '"';
}

function tp_props(comp) {
	var rows = [];
	for (var p = 0; p < comp.properties.numItems; p++) {
		var prop = comp.properties[p], v, err = '';
		try { v = prop.getValue(); } catch (e) { err = String(e); }
		rows.push('{"index":' + p + ',"name":' + tp_q(prop.displayName) + ',"type":' + tp_q(typeof v)
			+ ',"value":' + tp_q(v) + ',"error":' + tp_q(err) + '}');
	}
	return '[' + rows.join(',') + ']';
}

function tp_selection() {
	var seq = app.project.activeSequence;
	if (!seq) throw new Error('No active sequence');
	return seq.getSelection();
}

// The selected clips: every component's properties, plus the MOGRT component when there is one.
function tp_read() {
	try {
		var sel = tp_selection(), items = [];
		for (var i = 0; i < sel.length; i++) {
			var item = sel[i], comps = [], mgt = 'null';
			for (var c = 0; c < item.components.numItems; c++) {
				var comp = item.components[c];
				comps.push('{"index":' + c + ',"name":' + tp_q(comp.displayName) + ',"match":' + tp_q(comp.matchName)
					+ ',"props":' + tp_props(comp) + '}');
			}
			var isMgt = item.isMGT();
			if (isMgt) {
				var m = item.getMGTComponent();
				if (m) mgt = '{"name":' + tp_q(m.displayName) + ',"props":' + tp_props(m) + '}';
			}
			items.push('{"index":' + i + ',"name":' + tp_q(item.name) + ',"isMGT":' + (isMgt ? 'true' : 'false')
				+ ',"components":[' + comps.join(',') + '],"mgt":' + mgt + '}');
		}
		return '{"ok":true,"items":[' + items.join(',') + ']}';
	} catch (e) {
		return '{"ok":false,"error":' + tp_q(e) + '}';
	}
}

// compIndex -1 means the MOGRT component. Returns the value read back after setValue.
function tp_write(itemIndex, compIndex, propIndex, value) {
	try {
		var item = tp_selection()[itemIndex];
		var comp = compIndex < 0 ? item.getMGTComponent() : item.components[compIndex];
		var prop = comp.properties[propIndex];
		var before = prop.getValue();
		var result = prop.setValue(value, 1);
		var after = prop.getValue();
		return '{"ok":true,"result":' + tp_q(result) + ',"before":' + tp_q(before) + ',"after":' + tp_q(after) + '}';
	} catch (e) {
		return '{"ok":false,"error":' + tp_q(e) + '}';
	}
}
