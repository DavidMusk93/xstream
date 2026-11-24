//! Thread-safe in-process pub/sub event bus with slow-client coalescing.
//!
//! Ported from `core/events.py`. Each subscriber owns a bounded FIFO queue
//! (`DEFAULT_QUEUE_CAPACITY = 256`). When a subscriber falls behind and its
//! queue fills up, the bus drains stale payloads and enqueues a single
//! `sync.resync_required` marker rather than disconnecting the client.

use std::collections::{HashMap, VecDeque};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

/// Default maximum buffered events per subscriber before coalescing.
pub const DEFAULT_QUEUE_CAPACITY: usize = 256;

/// Opaque identifier for a registered subscriber.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct SubscriberId(u64);

impl SubscriberId {
    /// Returns the raw numeric identifier (for FFI / `PyO3` bridges).
    pub fn as_u64(self) -> u64 {
        self.0
    }

    /// Reconstructs a [`SubscriberId`] from its raw numeric identifier.
    pub fn from_u64(raw: u64) -> Self {
        Self(raw)
    }
}

/// Summary returned by [`EventBus::publish`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublishReport {
    /// Subscriber IDs that received either the payload or a resync marker.
    pub notified: Vec<SubscriberId>,
    /// Pairs of `(subscriber_id, dropped_count)` for slow clients that overflowed.
    pub coalesced: Vec<(SubscriberId, usize)>,
}

/// Thread-safe pub/sub bus shared across async handlers and background threads.
#[derive(Debug)]
pub struct EventBus {
    capacity: usize,
    next_id: AtomicU64,
    subscribers: Mutex<HashMap<SubscriberId, VecDeque<String>>>,
}

const _: () = {
    const fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<EventBus>();
};

impl Default for EventBus {
    fn default() -> Self {
        Self::new()
    }
}

impl EventBus {
    /// Creates a new bus with [`DEFAULT_QUEUE_CAPACITY`] buffered events per client.
    pub fn new() -> Self {
        Self::with_capacity(DEFAULT_QUEUE_CAPACITY)
    }

    /// Creates a new bus with a custom per-client queue capacity (minimum 1).
    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            capacity: capacity.max(1),
            next_id: AtomicU64::new(1),
            subscribers: Mutex::new(HashMap::new()),
        }
    }

    /// Registers a new subscriber and returns its [`SubscriberId`].
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn subscribe(&self) -> SubscriberId {
        let id = SubscriberId(self.next_id.fetch_add(1, Ordering::Relaxed));
        let mut subs = self.subscribers.lock().expect("event bus lock poisoned");
        subs.insert(id, VecDeque::with_capacity(self.capacity.min(64)));
        id
    }

    /// Removes a subscriber and drops its buffered events.
    ///
    /// Returns `true` if the subscriber existed.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn unsubscribe(&self, id: SubscriberId) -> bool {
        let mut subs = self.subscribers.lock().expect("event bus lock poisoned");
        subs.remove(&id).is_some()
    }

    /// Returns the number of currently subscribed clients.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn subscriber_count(&self) -> usize {
        let subs = self.subscribers.lock().expect("event bus lock poisoned");
        subs.len()
    }

    /// Broadcasts `payload` to all connected subscribers.
    ///
    /// If a subscriber's queue is full, all buffered items are drained and
    /// replaced with `resync_marker` so the client refreshes once instead of
    /// silently dropping events or disconnecting.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn publish(&self, payload: &str, resync_marker: &str) -> PublishReport {
        let mut subs = self.subscribers.lock().expect("event bus lock poisoned");
        let mut notified = Vec::with_capacity(subs.len());
        let mut coalesced = Vec::new();

        for (&id, queue) in subs.iter_mut() {
            if queue.len() < self.capacity {
                queue.push_back(payload.to_owned());
            } else {
                let dropped = queue.len();
                queue.clear();
                queue.push_back(resync_marker.to_owned());
                coalesced.push((id, dropped));
            }
            notified.push(id);
        }

        PublishReport {
            notified,
            coalesced,
        }
    }

    /// Pops the next buffered payload for `id`, or `None` if empty / unknown.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn try_recv(&self, id: SubscriberId) -> Option<String> {
        let mut subs = self.subscribers.lock().expect("event bus lock poisoned");
        subs.get_mut(&id).and_then(VecDeque::pop_front)
    }

    /// Drains all currently buffered payloads for `id` in FIFO order.
    ///
    /// # Panics
    ///
    /// Panics if the internal mutex is poisoned.
    pub fn drain(&self, id: SubscriberId) -> Vec<String> {
        let mut subs = self.subscribers.lock().expect("event bus lock poisoned");
        subs.get_mut(&id)
            .map(|q| q.drain(..).collect())
            .unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use std::thread;

    use super::*;

    #[test]
    fn subscribe_publish_and_unsubscribe() {
        let bus = EventBus::new();
        let s1 = bus.subscribe();
        let s2 = bus.subscribe();
        assert_eq!(bus.subscriber_count(), 2);

        let report = bus.publish(
            "{\"event\":\"ping\"}",
            "{\"event\":\"sync.resync_required\"}",
        );
        assert_eq!(report.notified.len(), 2);
        assert_eq!(report.coalesced, Vec::<(SubscriberId, usize)>::new());

        assert_eq!(bus.try_recv(s1).as_deref(), Some("{\"event\":\"ping\"}"));
        assert_eq!(bus.try_recv(s2).as_deref(), Some("{\"event\":\"ping\"}"));
        assert_eq!(bus.try_recv(s1), None);

        assert!(bus.unsubscribe(s1));
        assert!(!bus.unsubscribe(s1));
        assert_eq!(bus.subscriber_count(), 1);
    }

    #[test]
    fn slow_client_coalesces_to_resync_marker() {
        let bus = EventBus::with_capacity(2);
        let slow = bus.subscribe();
        let fast = bus.subscribe();

        let marker = "{\"event\":\"sync.resync_required\"}";
        bus.publish("e1", marker);
        assert_eq!(bus.try_recv(fast).as_deref(), Some("e1"));
        bus.publish("e2", marker);
        assert_eq!(bus.try_recv(fast).as_deref(), Some("e2"));

        // Third publish overflows `slow` (cap=2) -> drains 2, enqueues marker
        let report = bus.publish("e3", marker);
        assert_eq!(report.coalesced, vec![(slow, 2)]);
        assert_eq!(bus.drain(slow), vec![marker.to_owned()]);
        assert_eq!(bus.drain(fast), vec!["e3".to_owned()]);
    }

    #[test]
    fn concurrent_publishers_and_subscribers_stay_consistent() {
        let bus = Arc::new(EventBus::with_capacity(64));
        let sub = bus.subscribe();

        let mut threads = Vec::new();
        for t in 0..4 {
            let b = Arc::clone(&bus);
            threads.push(thread::spawn(move || {
                for i in 0..10 {
                    let _ = b.publish(&format!("t{t}-{i}"), "resync");
                }
            }));
        }
        for th in threads {
            th.join().unwrap();
        }

        let msgs = bus.drain(sub);
        assert_eq!(msgs.len(), 40);
    }
}
