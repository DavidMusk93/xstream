//! Read one JSON envelope on stdin: {"event":"...", "data":{...}}
//! Print Telegram HTML on stdout (Bot API HTML parse_mode).

use serde::Deserialize;
use serde_json::Value;
use std::io::{self, Read};

#[derive(Deserialize)]
struct Envelope {
    event: String,
    data: Value,
}

fn main() {
    if let Err(e) = run() {
        eprintln!("tg-lint: {e}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let mut buf = String::new();
    io::stdin()
        .read_to_string(&mut buf)
        .map_err(|e| e.to_string())?;
    let env: Envelope = serde_json::from_str(&buf).map_err(|e| e.to_string())?;
    let out = render(&env.event, &env.data);
    print!("{out}");
    Ok(())
}

fn render(event: &str, data: &Value) -> String {
    match event {
        "sync.completed" => sync_completed(data),
        "sync.error" => sync_error(data),
        "sync.started" => sync_started(data),
        "metrics.alert" => metrics_alert(data),
        "magnets.check_completed" => magnets_done(data),
        "magnets.check_error" => magnets_error(data),
        "magnets.purged" => magnets_purged(data),
        "magnets.check_started" => line_header("🧲 Magnet check started", data.get("scope").and_then(|v| v.as_str()).unwrap_or("?")),
        "star.ready" => star_ready(data),
        "star.social" => social_stars(data),
        "creator.social" => social_creators(data),
        _ => generic(event, data),
    }
}

fn sync_started(data: &Value) -> String {
    let trigger = data.get("trigger").and_then(|v| v.as_str()).unwrap_or("?");
    format!(
        "🔄 <b>Library sync started</b>\n{}",
        kv("Trigger", &esc(trigger))
    )
}

fn sync_completed(data: &Value) -> String {
    let new = data.get("total_new").and_then(|v| v.as_i64()).unwrap_or(0);
    let updated = data.get("total_updated").and_then(|v| v.as_i64()).unwrap_or(0);
    let elapsed = data.get("elapsed").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let trigger = data.get("trigger").and_then(|v| v.as_str()).unwrap_or("sync");

    let mut out = String::from("📚 <b>Library sync complete</b>\n\n");
    out.push_str(&format!(
        "{} · {}\n",
        kv("New", &format!("<b>{new}</b>")),
        kv("Updated", &format!("<b>{updated}</b>")),
    ));
    out.push_str(&format!("<i>{} · {elapsed:.1}s</i>\n", esc(trigger)));

    if let Some(stars) = data.get("star_updates").and_then(|v| v.as_array()) {
        for star in stars {
            out.push_str("\n");
            out.push_str(&render_star_block(star));
        }
    }

    if let Some(failed) = data.get("failed").and_then(|v| v.as_array()) {
        if !failed.is_empty() {
            let names: Vec<String> = failed
                .iter()
                .filter_map(|f| f.as_str().map(|s| esc(s)))
                .collect();
            if !names.is_empty() {
                out.push_str(&format!(
                    "\n⚠️ {}\n",
                    kv("Failed stars", &format!("<i>{}</i>", names.join(", ")))
                ));
            }
        }
    }

    if new == 0 && data.get("star_updates").and_then(|v| v.as_array()).is_none() {
        if let Some(lines) = data.get("log_lines").and_then(|v| v.as_array()) {
            let mut tail = String::from("<i>No structured updates; tail log:</i>\n");
            for ln in lines.iter().take(8) {
                if let Some(s) = ln.as_str() {
                    tail.push_str(&format!("  {}\n", esc(s)));
                }
            }
            out.push_str(&blockquote(&tail, false));
        }
    }

    out
}

fn render_star_block(star: &Value) -> String {
    let name = star.get("name").and_then(|v| v.as_str()).unwrap_or("?");
    let code = star.get("code").and_then(|v| v.as_str()).unwrap_or("");
    let count = star.get("count").and_then(|v| v.as_i64()).unwrap_or(0);

    let mut head = format!("⭐ <b>{}</b>", esc(name));
    if !code.is_empty() {
        head.push_str(&format!(" · <code>{}</code>", esc(code)));
    }
    head.push_str(&format!("\n<b>{count}</b> new title(s)\n"));

    let titles = star
        .get("new_titles")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    if titles.is_empty() {
        return head;
    }

    let mut body = String::new();
    for t in &titles {
        body.push_str(&render_title_line(t));
        body.push('\n');
    }
    let expandable = titles.len() > 3;
    head.push_str(&blockquote(body.trim_end(), expandable));
    head
}

fn render_title_line(t: &Value) -> String {
    let tc = t.get("code").and_then(|v| v.as_str()).unwrap_or("");
    let title = t.get("title").and_then(|v| v.as_str()).unwrap_or("");
    let date = t.get("date").and_then(|v| v.as_str()).unwrap_or("");
    let res = t.get("resolution").and_then(|v| v.as_str()).unwrap_or("");
    let size = t.get("size").and_then(|v| v.as_str()).unwrap_or("");
    let meta: Vec<&str> = [date, res, size]
        .into_iter()
        .filter(|s| !s.is_empty())
        .collect();

    let mut line = String::from("• <code>");
    line.push_str(&esc(tc));
    line.push_str("</code>");
    if !title.is_empty() {
        line.push_str("\n  ");
        line.push_str(&esc(title));
    }
    if !meta.is_empty() {
        line.push_str("\n  <i>");
        line.push_str(&esc(&meta.join(" · ")));
        line.push_str("</i>");
    }
    line
}

fn sync_error(data: &Value) -> String {
    format!(
        "⛔ <b>Sync failed</b>\n\n{}\n\n{}",
        kv(
            "Trigger",
            &format!(
                "<code>{}</code>",
                esc(data.get("trigger").and_then(|v| v.as_str()).unwrap_or("?"))
            )
        ),
        blockquote(
            &format!(
                "<pre>{}</pre>",
                esc(data.get("error").and_then(|v| v.as_str()).unwrap_or("unknown"))
            ),
            false,
        )
    )
}

fn metrics_alert(data: &Value) -> String {
    let kind = data.get("kind").and_then(|v| v.as_str()).unwrap_or("alert");
    let code = data.get("code").and_then(|v| v.as_str()).unwrap_or("-");
    let star = data.get("star_code").and_then(|v| v.as_str()).unwrap_or("-");
    let detail = data.get("detail").and_then(|v| v.as_str()).unwrap_or("");
    let headline = match kind {
        "play_timeout" => "Play timeout",
        "play_error" => "Play error",
        other => other,
    };
    format!(
        "📉 <b>Metrics · {}</b>\n\n{}\n{}\n\n{}",
        esc(headline),
        kv("Work", &format!("<code>{}</code>", esc(code))),
        kv("Star", &format!("<code>{}</code>", esc(star))),
        blockquote(
            &format!("<pre>{}</pre>", esc(detail)),
            detail.lines().count() > 4,
        ),
    )
}

fn magnets_done(data: &Value) -> String {
    format!(
        "🧲 <b>Magnet check complete</b>\n\n\
         {}\n\
         {}\n\
         {}\n\
         {}\n\
         <i>{:.1}s</i>",
        kv(
            "Scope",
            &format!(
                "<code>{}</code>",
                esc(data.get("scope").and_then(|v| v.as_str()).unwrap_or("?"))
            )
        ),
        kv(
            "Total",
            &format!("<b>{}</b>", data.get("total").and_then(|v| v.as_i64()).unwrap_or(0))
        ),
        kv(
            "Alive",
            &format!("<b>{}</b>", data.get("alive").and_then(|v| v.as_i64()).unwrap_or(0))
        ),
        format!(
            "{} · {}",
            kv(
                "Dead",
                &format!("{}", data.get("dead").and_then(|v| v.as_i64()).unwrap_or(0))
            ),
            kv(
                "Swapped",
                &format!("{}", data.get("swapped").and_then(|v| v.as_i64()).unwrap_or(0))
            ),
        ),
        data.get("elapsed").and_then(|v| v.as_f64()).unwrap_or(0.0),
    )
}

fn magnets_error(data: &Value) -> String {
    format!(
        "⛔ <b>Magnet check failed</b>\n\n{}\n\n{}",
        kv(
            "Scope",
            &format!(
                "<code>{}</code>",
                esc(data.get("scope").and_then(|v| v.as_str()).unwrap_or("?"))
            )
        ),
        blockquote(
            &format!(
                "<pre>{}</pre>",
                esc(data.get("error").and_then(|v| v.as_str()).unwrap_or("?"))
            ),
            false,
        )
    )
}

fn magnets_purged(data: &Value) -> String {
    let deleted = data
        .get("deleted")
        .and_then(|v| v.as_i64())
        .or_else(|| data.get("count").and_then(|v| v.as_i64()))
        .unwrap_or(0);
    format!(
        "🗑 <b>Purge complete</b>\n\n{}\n{}",
        kv("Removed", &format!("<b>{deleted}</b> unplayable rows")),
        kv(
            "TTL",
            &format!(
                "<i>{} days</i>",
                data.get("ttl_days").and_then(|v| v.as_i64()).unwrap_or(0)
            )
        ),
    )
}

fn star_ready(data: &Value) -> String {
    format!(
        "⭐ <b>Star shelf ready</b>\n\n{}\n{}\n{}",
        kv(
            "Code",
            &format!(
                "<code>{}</code>",
                esc(data.get("code").and_then(|v| v.as_str()).unwrap_or("?"))
            )
        ),
        kv("Name", &esc(data.get("name").and_then(|v| v.as_str()).unwrap_or(""))),
        kv(
            "Titles",
            &format!("<b>{}</b>", data.get("titles_count").and_then(|v| v.as_i64()).unwrap_or(0))
        ),
    )
}

fn social_stars(data: &Value) -> String {
    let stars: Vec<String> = data
        .get("stars")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|v| v.as_str().map(esc)).collect())
        .unwrap_or_default();
    format!(
        "𝕏 <b>Stars feed updated</b>\n\n{}",
        if stars.is_empty() {
            "<i>Feed refreshed</i>".to_string()
        } else {
            blockquote(&stars.join("\n"), stars.len() > 5)
        }
    )
}

fn social_creators(data: &Value) -> String {
    if data.get("removed").and_then(|v| v.as_bool()) == Some(true) {
        let handles: Vec<String> = data
            .get("handles")
            .and_then(|v| v.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(|h| format!("@{}", esc(h))))
                    .collect()
            })
            .unwrap_or_default();
        return format!(
            "𝕏 <b>Creator removed</b>\n\n{}",
            blockquote(&handles.join("\n"), false)
        );
    }
    let handles: Vec<String> = data
        .get("handles")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|v| v.as_str().map(|h| format!("@{}", esc(h))))
                .collect()
        })
        .unwrap_or_default();
    format!(
        "𝕏 <b>Creators feed updated</b>\n\n{}",
        if handles.is_empty() {
            "<i>Feed refreshed</i>".to_string()
        } else {
            blockquote(&handles.join("\n"), handles.len() > 5)
        }
    )
}

fn line_header(title: &str, sub: &str) -> String {
    format!("{title}\n<i>{}</i>", esc(sub))
}

fn generic(event: &str, data: &Value) -> String {
    format!(
        "📡 <b>xstream</b>\n{}\n\n{}",
        kv("Event", &format!("<code>{}</code>", esc(event))),
        blockquote(
            &format!(
                "<pre>{}</pre>",
                esc(&data.to_string().chars().take(800).collect::<String>())
            ),
            false,
        )
    )
}

fn kv(label: &str, value: &str) -> String {
    if value.is_empty() {
        return String::new();
    }
    format!("<b>{label}:</b> {value}")
}

fn blockquote(body: &str, expandable: bool) -> String {
    if body.trim().is_empty() {
        return String::new();
    }
    if expandable {
        format!("<blockquote expandable>{body}</blockquote>\n")
    } else {
        format!("<blockquote>{body}</blockquote>\n")
    }
}

fn esc(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}
