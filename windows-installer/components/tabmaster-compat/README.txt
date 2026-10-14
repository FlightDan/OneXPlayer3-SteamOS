OXP3 compatibility patch 2.15.1+oxp3.1
Base: unmodified TabMaster 2.15.1 from the official Decky store.
Steam may legitimately leave m_achievementProgress undefined.
Use size 0 while absent, retain the subscription for later cache initialization,
and skip missing entries in achievement-count filters.
GetAchievementProgress remains unchanged so Steam can queue cache updates.
Corresponding modified TypeScript and unified diffs are included.
The source map retains upstream mappings; runtime auto-loading is disabled.
Original GPL-3.0/BSD notices are preserved.
