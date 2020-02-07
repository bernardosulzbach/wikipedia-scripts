// This script is HEAVILY based on [[User:Anomie/lastmod.js]].

importStylesheet('User:BernardoSulzbach/last-modified.css');

if (typeof (window.LastModDateFormat) == 'undefined') window.LastModDateFormat = "dmy";
if (typeof (window.LastModRelative) == 'undefined') window.LastModRelative = false;
if (typeof (window.LastModUseUTC) == 'undefined') window.LastModUseUTC = false;
if (typeof (window.LastModMonths) == 'undefined') window.LastModMonths = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

if (mw.config.get('wgNamespaceNumber') >= 0) mw.loader.using('mediawiki.util', function () {
    $(document).ready(function () {
        var ins = document.getElementById('siteSub');
        if (!ins) return;

        var articleId = mw.config.get('wgArticleId');
        $.ajax({
            url: mw.util.wikiScript('api'),
            dataType: 'json',
            type: 'POST',
            data: {
                format: 'json',
                action: 'query',
                pageids: articleId,
                prop: 'revisions',
                rvprop: 'timestamp'
            },
            success: function (r, sts, xhr) {
                if (typeof (r.query.pages[articleId].revisions[0].timestamp) == 'undefined') return;
                m = r.query.pages[articleId].revisions[0].timestamp.match(/^(\d\d\d\d)-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)Z$/);
                let dt;
                if (window.LastModRelative) {
                    dt = [];
                    const n = new Date();
                    let dy = n.getUTCFullYear() - m[1];
                    let dm = n.getUTCMonth() + 1 - m[2];
                    let dd = n.getUTCDate() - m[3];
                    let dh = n.getUTCHours() - m[4];
                    let di = n.getUTCMinutes() - m[5];
                    if (di < 0) {
                        di += 60;
                        dh--;
                    }
                    if (dh < 0) {
                        dh += 60;
                        dd--;
                    }
                    if (dd < 0) {
                        const nn = n;
                        nn.setUTCDate(0);
                        dd += nn.getDate();
                        dm--;
                    }
                    if (dm < 0) {
                        dm += 12;
                        dy--;
                    }
                    if (dy >= 0) {
                        // TODO: change these to use a function that automates pluralization.
                        if (dy !== 0) dt.push(dy + ' year' + ((dy === 1) ? '' : 's'));
                        if (dm !== 0) dt.push(dm + ' month' + ((dm === 1) ? '' : 's'));
                        if (dd !== 0) dt.push(dd + ' day' + ((dd === 1) ? '' : 's'));
                        if (dy === 0 && dm === 0 && dd < 7) {
                            if (dh !== 0) dt.push(dh + ' hour' + ((dh === 1) ? '' : 's'));
                            if (dd < 2 && di !== 0) dt.push(di + ' minute' + ((di === 1) ? '' : 's'));
                        }
                    }
                    if (dt.length === 0) dt = 'less than a minute ago';
                    else dt = 'about ' + dt.join(', ') + ' ago';
                } else {
                    if (window.LastModUseUTC) {
                        m[2] -= 1;
                    } else {
                        dt = new Date(Date.UTC(m[1], m[2] - 1, m[3], m[4], m[5], m[6]));
                        m[1] = dt.getFullYear();
                        m[2] = dt.getMonth();
                        m[3] = dt.getDate();
                        // TODO: change these to use a function that pads with 0.
                        m[4] = dt.getHours().toString();
                        if (m[4].length === 1) m[4] = '0' + m[4];
                        m[5] = dt.getMinutes().toString();
                        if (m[5].length === 1) m[5] = '0' + m[5];
                        m[6] = dt.getSeconds().toString();
                        if (m[6].length === 1) m[6] = '0' + m[6];
                    }

                    if (window.LastModDateFormat === 'dmy') {
                        dt = m[3] + ' ' + window.LastModMonths[m[2]] + ' ' + m[1];
                    } else if (window.LastModDateFormat === 'mdy') {
                        dt = window.LastModMonths[m[2]] + ' ' + m[3] + ', ' + m[1];
                    } else {
                        m[2]++;
                        if (m[2] < 10) m[2] = '0' + m[2];
                        m[3] = m[3].toString();
                        if (m[3].length === 1) m[3] = '0' + m[3];
                        dt = m[1] + '-' + m[2] + '-' + m[3];
                    }
                    dt += ' ' + m[4] + ':' + m[5];
                }
                const s = document.createElement('span');
                s.className = 'last-modified-header';
                s.appendChild(document.createTextNode('Last modified ' + dt));
                ins.parentNode.insertBefore(s, ins);
            },
            error: function (xhr, textStatus, errorThrown) {
                throw new Error('AJAX error: ' + textStatus + ' ' + errorThrown);
            }
        });
    });
});
