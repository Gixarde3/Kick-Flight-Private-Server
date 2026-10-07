# Social and crown-ranking restoration contract

This note records the client contract used by the server handlers. The DTO names, fields, and route strings were checked against the shipped IL2CPP dump (`dump.cs`) and the route string references in the 2.11.0 `libil2cpp.so`; the dump is kept with the local RE artifacts, not tracked in this repository. RVA values below are module-relative and identify the route string or client call site in that build. Static references were inspected using the repository's `scripts/re/README.md` workflow; no ADB/runtime trace was used for this work.

## Social screen

`SocialDisplayView.TabType` is Follow=0, Follower=1, Search=2. The visible `Follow`, `Followers`, and `Search` tabs map to these three data flows. `GetFollowList` (`0x14F91E4`), `GetFollowerList` (`0x14F9338`), and `GetIdSearchList` (`0x14F9488`) lead to the endpoints below. The search tab's ID path is distinct from the SNS/Facebook/Twitter search path (`GetSocialSearchList`, `0x14F9610`); no external SNS integration is inferred here.

| UI action | Request and response | Expected screen data |
| --- | --- | --- |
| Follow tab | `POST /follow/index`: `{page:uint,teamBattleInvitationFlag:bool}` → `{userProfileList,followCount,newFollowerCount}` (`0x320CF40`) | The caller's directed outgoing follow list, paged; count and unread inbound-follower count. |
| Followers tab | `POST /follower/index`: `{page:uint}` → `{userProfileList,followerCount,newFollowerCount}` (`0x320D488`) | Accounts that follow the caller; `newFlag` marks unread inbound edges. |
| Mark followers read | `POST /follower/read`: `{followerUserIdList:string[]}` → `{}` (`0x320D374`) | Marks only the listed inbound followers read. |
| Follow / unfollow | `POST /follow/add` or `/follow/remove`: `{followUserId:string}` → `{}` (`0x320CA88`, `0x320CE2C`) | Directed relationship; repeated add/remove is idempotent. `followStatus` is 1 for an outgoing follow, 0 for none, and 2 only for a separate real-friend relation. |
| Check follow state | `POST /follow/search`: `{userIdList:string[]}` → `{followUserIdList:string[]}` (`0x320D130`) | Returns the supplied IDs the caller follows. |
| ID Search | `POST /user/search`: `{displayUserId:long}` → `{userProfile}` | Looks up an existing persisted display ID. Unknown IDs return the normal nonzero app status instead of a fabricated player. |
| Follow online | `POST /follow/online`: empty request → `{userProfileList}` (`0x320CCCC`) | Online subset of the caller's followed profiles. |

`ResponseUserProfile` carries `userId`, `displayUserId`, `name`, `honorId`, `userFrameList`, `kickerId`, `kickerCostumeId`, `onlineFlag`, `battleFlag`, `officialFlag`, `languageCode`, `followStatus`, `newFlag`, `userBattleRankList`, `snsUserName`, `snsScreenName`, and `snsUserImageUrl`.

The `teamBattleInvitationFlag` request field is present on `/follow/index` (`FollowRequestData`, RVA `0x320CC1C`). Separately, the home `InvitationNoticePresenter` calls `AddNotification(FollowOnlineResponseData)` at `0x15907A4`, and its `Initialize` continuation receives that online list at `0x1591F38`; the dedicated endpoint is `/follow/online`. The dump proves these fields/call paths, but does not expose the C# method bodies needed to establish a filtering rule for `teamBattleInvitationFlag`; the server currently returns the caller's follow list for either value. Online invitations return followed profiles with an authenticated request observed in the last 11 minutes. The client calls `/user/online` every 600 seconds with an empty callback (noted in `DemoSessionApi.cs` maintenance documentation); that request refreshes activity. This is an activity-based approximation, not a transport connection signal: players without a request for 11 minutes expire, and all activity timestamps reset on process restart. Team-recruitment invitation data is a separate flow and is not fabricated by these social handlers.

The `SocialDisplayPresenter` exposes `SetFollowerNotificationCount(int)` (`0x14F8D28`) and passes `newFollowerCount` into both follow/follower scroller updates (`0x14FA250`, `0x14FA5FC`). Its disable callback posts the `ReadFollowers` IDs (`0x14F9794`); this is why unread state is stored per incoming follow edge and cleared only for IDs submitted by that client. No separate login/home DTO field for follow counts appears in the inspected dump; the confirmed badge/count path is the social list response.

`Search` shows ID, Facebook, and Twitter choices in the supplied screen. The binary exposes `/user/search` for display-ID lookup. Facebook/Twitter use a separate SNS search/disconnection family; the existing DTOs do not provide an external account search service here, so this restoration does not claim or fabricate Facebook/Twitter results.

The profile window formats the numeric display ID through `common.userIdTitleFormat`. For stored player IDs below `100000000000`, the public display ID is `100000000000 + playerId`; existing IDs at or above that base pass through unchanged. Search checks an exact stored ID before decoding this namespace, preserving any pre-existing long ID. The Translation master uses `User ID: {0:D12}`. These IDs are a response/search mapping only: `players.id`, session keys, follows, real-friend edges, and ranks keep their existing values, and the mapping requires no database migration.

The `Invite Friend`/QR path uses `POST /realFriend/token` with an empty request and `{token:string}` response (route RVA `0x3210818`). `RealFriendDetailWindow.OpenQRCreateWindow` (`0x16C8B1C`) requests it. Scanning a QR calls `POST /realFriend/apply` with `{token:string}` and expects `{}` (route RVA `0x321066C`; caller in `QRReadWindow.<ReadCoroutine>d__8.MoveNext`, `0x16C0BE0`). The relationship is symmetric and separate from follows: applying does not create a Follow edge. Tokens are opaque, stable per owner, reusable for multiple invitees, and an apply is idempotent for a pair; invalid, self-owned, or unknown tokens fail.

## Crown ranking screen

The crown window asks only for `battleRuleId`; the request carries no player ID or region. The client value can be stale after an hourly mode rotation, so the server chooses the active ranked rule from its UTC clock for every crown tab. Its four request constructors route as follows:

| Crown tab | Endpoint | Client response setter / call site | Server behavior |
| --- | --- | --- | --- |
| World | `/ranking/index` | `SetResponseWorldRankingData` `0x15E1850`, caller `0x15E18F8` | Global named-player ladder for the translated `battleRuleType`. |
| Personal | `/ranking/user` | `SetResponseUserRankingData` `0x15E1964`, caller `0x15E1A0C` | A window of up to 11 rows around the caller's global position; caller's own `battleRanking` is also populated. |
| Follow | `/ranking/follow` | `SetResponseFollowRankingData` `0x15E1A78`, caller `0x15E1B20` | Ranking rows limited to accounts the caller follows, with their global positions. |
| Local | `/ranking/region` | `SetResponseRegionRankingData` `0x15E1B8C`, caller `0x15E1C34` | Uses the server population as the current fallback. Neither this request nor persisted player profiles provide verifiable region metadata, so this implementation does not infer region from language. |

The first three responses contain `{battleRankingList,battleRanking,nextRewardRemainingBattlePoint,appSeasonMatchResult}`. Region contains `{battleRankingList,appSeasonMatchResult}`. Each ranking request sends `{battleRuleId:int}`. The client response row is `ResponseBattleRanking`: `userId`, `name`, `honorId`, `kickerId`, `kickerCostumeId`, `languageCode`, `followStatus`, `rank`, `battlePoint`, `number`, and `percentile`.

In `SeasonRankingInfo`, `rank` and `number` are separate values: `rank` is the league/tier used for the division badge, `number` is the player's position, and `battlePoint` is the points display. The footer's `- / -pt` is the caller's own ranking/reward-progress area; the handler returns the caller's actual points, rank and global position when present. The screen does not consume `percentile` into `SeasonRankingInfo`; the server currently supplies 0. `appSeasonMatchResult` is returned with the response schema but uses the neutral no-season-result object rather than inventing a season outcome.

For each request, the server resolves `RankedModeRotation.RuleIdAt(serverUtcNow)` through the served `BattleRule` master to `battleRuleType`; the request's `battleRuleId` is ignored for ladder selection because it reflects client state and may be absent or stale. Points and tier remain stored per translated type, and the crown queries are projections that do not modify those saved rank rows. Results sort by points descending then player ID ascending, and `number` remains one-based global position even in the Follow-filtered list. The endpoint test advances a fake clock across hour boundaries and checks all four tabs against distinct seeded ladders while sending stale rule IDs.

## Persistence and checks

PostgreSQL migration v2 adds three social tables alongside the existing player/session/rank schema; `schema_meta` stores the applied migration versions:

| Table | Persisted contract |
| --- | --- |
| `player_follows` | Directed `(follower_id,followed_id)` edge, creation timestamp, nullable `read_at`; unique pair and no self-edge. |
| `real_friend_tokens` | One opaque reusable token per owner; token is unique and stable after first creation. |
| `player_real_friends` | Canonical `(player_low_id,player_high_id)` pair for a symmetric real-friend relation, separate from follows. |
| `schema_meta` | Migration version marker; schema version 2 is applied transactionally under the store's PostgreSQL advisory lock. |

The local JSON store persists the same graph, token-owner mapping, read state, and canonical real-friend pairs in `data/users/_social.json`; rank values remain in the existing rank store. There is no manual migration step: constructing `PostgresPlayerStore` applies any pending numbered migrations, preserving the v1 player/session/rank tables and adding v2 objects. Deployment still follows the repository's normal reviewed PR/pipeline procedure; this change does not run a production migration or deploy.

Verification covered HTTP requests using two independently authenticated sessions plus direct store rank seeding: directed add/remove and idempotence, counts and unread/read behavior, search intersection, token stability/reuse, idempotent QR apply, separation of real-friend from follow, invalid/self/unknown target rejection, unknown ID lookup, invalid page fallback, recent-activity online expiry/refresh with a fake clock, and all four ranking tabs with tier/points/position assertions. The store tests cover durable social state, deterministic ranks, and token/friend persistence; PostgreSQL migration tests cover v1-to-v2 upgrade and edge/token state. The final full suite passed 188 tests with 0 failures and 1 opt-in PostgreSQL test skipped when no connection string is configured. The PostgreSQL migration test separately passed against an isolated PostgreSQL instance using a v1 schema, including repeated startup and future-version rejection.

Known limits: Local ranking falls back to all named players on this server because neither the crown request nor persisted `PlayerProfile` has reliable region data. SNS search has no external provider integration. `appSeasonMatchResult` is kept schema-complete with a neutral no-result object; there is no fabricated season reward/result, and replay behavior is outside this social/ranking restoration. External live-user and Photon behavior was not validated in this code-only verification.
