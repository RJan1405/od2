# 🚀 Odnix Platform — API Documentation

**System Context**: All API requests should include the header:  
`Authorization: Token <your_auth_token>`

---

## 🔐 1. Authentication & Security
| Endpoint                   | Method |             Function              |            Description               |
| :---                       | :---   | :---                              | :---                                 |
| `/api/login/`              | `POST` | `api_auth.api_login`              | User login (returns Auth Token)      |
| `/api/logout/`             | `POST` | `api_auth.api_logout`             | Logs out current session             |
| `/api/register/`           | `POST` | `api_auth.api_register`           | Standard user registration           |
| `/api/check-availability/` | `POST` | `api_auth.api_check_availability` | Check username/email/phone available |
| `/api/firebase-register/`  | `POST` | `api_auth.api_firebase_register`  | Registration via Firebase Phone token|
| `/api/verify-phone-otp/`   | `POST` | `api_auth.api_verify_phone_otp`   | Local OTP verification for phone     |
| `/api/csrf/`               | `GET`  | `api_auth.get_csrf_token`         | Fetch CSRF token for secure web      |
| `/verify-email/<token>/`   | `GET`  | `views.verify_email`              | Link-based email verification        |
| `/verify-email-otp/`       | `POST` | `views.verify_otp_view`           | OTP-based email verification         |

---

## 👤 2. User & Profile Management
| Endpoint                            | Method    |             Function              |            Description               |
| :---                                | :---      | :---                              | :---                                 |
| `/api/profile/`                     | `GET/POST`| `api_auth.api_profile`            | Get/Update own profile data          |
| `/api/profile/<str:username>/`      | `GET`     | `api_auth.api_user_profile`       | Get public profile of another user   |
| `/api/profile/<username>/followers/`| `GET`     | `views.get_profile_followers`     | List of user's followers             |
| `/api/profile/<username>/following/`| `GET`     | `views.get_profile_following`     | List of people the user follows      |
| `/api/user/heartbeat/`              | `POST`    | `views.user_heartbeat`            | Update "Last Seen" timestamp         |
| `/api/user/<int:id>/status/`        | `GET`     | `views.get_user_online_status`    | Check if user is currently online    |
| `/api/user/update-theme/`           | `POST`    | `views.update_theme`              | Save theme preference (Dark/Light)   |

---

## 💬 3. Chat Core & Messaging
| Endpoint                           | Method |             Function               |            Description               |
| :---                               | :---   | :---                               | :---                                 |
| `/api/chats/`                      | `GET`  | `views.get_chats_api`              | Inbox list of all conversations      |
| `/api/create-chat/`                | `POST` | `views.create_chat`                | Start/Resume a 1v1 conversation      |
| `/api/chat/<int:id>/messages/`     | `GET`  | `views.get_chat_messages`          | Paginated message history            |
| `/api/send-message/`               | `POST` | `views.send_message`               | Send message (Text/Media/OTV)        |
| `/api/edit-message/<int:id>/`      | `POST` | `views.edit_message`               | Edit a sent message                  |
| `/api/delete-message-for-me/<id>/` | `POST` | `views.delete_message_for_me`      | Delete message for self              |
| `/api/delete-message-for-everyone/`| `POST` | `views.delete_message_for_everyone`| Delete message for everyone          |
| `/api/consume-message/<int:id>/`   | `POST` | `views.consume_one_time_message`   | Self-destruct a OTV message          |
| `/api/message/<id>/context-menu/`  | `GET`  | `views.get_message_context_menu`   | Load valid actions for a message     |
| `/api/message/context-action/`     | `POST` | `views.message_context_action`     | Execute a context action             |

---

## ✅ 4. Read Receipts & Unread Status
| Endpoint                           | Method |             Function              |            Description               |
| :---                               | :---   | :---                              | :---                                 |
| `/api/messages/mark-read/`         | `POST` | `read_receipts.mark_messages_read`| Bulk mark specific messages as read  |
| `/api/chat/<id>/mark-read/`        | `POST` | `read_receipts.mark_chat_read`    | Mark entire chat as read             |
| `/api/unread-counts/`              | `GET`  | `read_receipts.get_unread_counts` | Global unread badge counts           |
| `/api/message/<id>/read-status/`   | `GET`  | `views.get_message_read_status`   | Detailed "Read by" info              |
| `/api/chat/<id>/read-status/`      | `GET`  | `views.get_chat_read_status`      | Overview of read status for chat     |
| `/api/chat/<id>/typing/`           | `POST` | `views.update_typing_status`      | Toggle typing status (ON/OFF)        |
| `/api/chat/<id>/typing-status/`    | `GET`  | `views.get_typing_status`         | See who is typing right now          |

---

## 🌟 5. Starred, Pinned & Reactions
| Endpoint                           | Method |             Function              |            Description               |
| :---                               | :---   | :---                              | :---                                 |
| `/api/star-message/<int:id>/`      | `POST` | `views.toggle_star_message`       | Star/Unstar a specific message       |
| `/api/starred-messages/`           | `GET`  | `views.get_starred_messages`      | List all your starred messages       |
| `/api/message/<id>/is-starred/`    | `GET`  | `views.is_message_starred`        | Check star status for one message    |
| `/api/pin-message/<int:id>/`       | `POST` | `views.pin_message`               | Pin message to top of chat           |
| `/api/unpin-message/<int:id>/`     | `POST` | `views.unpin_message`             | Unpin message                        |
| `/api/chat/<id>/pinned-messages/`  | `GET`  | `views.get_pinned_messages`       | Fetch pinned list for a chat         |
| `/api/pin-chat/<int:chat_id>/`     | `POST` | `views.pin_chat`                  | Pin conversation to top of Inbox     |
| `/api/unpin-chat/<int:chat_id>/`   | `POST` | `views.unpin_chat`                | Unpin conversation                   |
| `/api/react-message/<int:id>/`     | `POST` | `views.react_to_message`          | Emoji reaction (Add/Remove)          |

---

## ✍️ 6. Scribes (Social Posts)
| Endpoint                           | Method |             Function              |            Description               |
| :---                               | :---   | :---                              | :---                                 |
| `/api/explore-feed/`               | `GET`  | `views.api_explore_feed`          | Global social feed JSON              |
| `/api/post-scribe/`                | `POST` | `views.post_scribe`               | Create new post                      |
| `/api/repost/`                     | `POST` | `views.api_repost`                | Quote/Repost a Post or Video         |
| `/api/toggle-like/`                | `POST` | `views.toggle_like`               | Like/Unlike post                     |
| `/api/toggle-dislike/`             | `POST` | `views.toggle_dislike`            | Dislike/Un-dislike post              |
| `/api/save-scribe/`                | `POST` | `views.toggle_save_scribe`        | Save post to your collection         |
| `/api/delete-post/`                | `POST` | `views.delete_post`               | Delete your own post                 |
| `/api/report-post/`                | `POST` | `views.report_post`               | Report a post to moderators          |
| `/api/scribe/<int:id>/comments/`   | `GET`  | `views.get_scribe_comments`       | Load post discussion                 |
| `/api/add-comment/`                | `POST` | `views.add_comment`               | Post a text/reply comment            |

---

## 🎬 7. Omzos (Vertical Video)
| Endpoint                           | Method |             Function              |            Description               |
| :---                               | :---   | :---                              | :---                                 |
| `/api/omzo/batch/`                 | `GET`  | `views.get_omzo_batch`            | Cursor-paginated video feed          |
| `/api/omzo/upload/`                | `POST` | `views.upload_omzo`               | Upload a short video                 |
| `/api/omzo/like/`                  | `POST` | `views.toggle_omzo_like`          | Like/Unlike video                    |
| `/api/omzo/dislike/`               | `POST` | `views.toggle_omzo_dislike`       | Dislike/Un-dislike video             |
| `/api/omzo/track-view/`            | `POST` | `views.track_omzo_view`           | Mark video as viewed                 |
| `/api/save-omzo/`                  | `POST` | `views.toggle_save_omzo`          | Save video to collection             |
| `/api/omzo/<id>/comments/`         | `GET`  | `views.get_omzo_comments`         | Video comment list                   |
| `/api/omzo/comment/`               | `POST` | `views.add_omzo_comment`          | Post video comment                   |
| `/api/omzo/report/`                | `POST` | `views.report_omzo`               | Report a video for safety            |

---

## 📖 8. Stories
| Endpoint                           | Method |             Function              |            Description               |
| :---                               | :---   | :---                              | :---                                 |
| `/api/following-stories/`          | `GET`  | `views.get_following_stories`     | Stories from your follow list        |
| `/api/create-story/`               | `POST` | `views.create_story`              | Post new 24h story                   |
| `/api/story/<int:story_id>/`       | `GET`  | `views.view_story`                | View a specific story detail         |
| `/api/user-stories/<username>/`    | `GET`  | `views.get_user_stories`          | Get all stories for a specific user  |
| `/api/story/mark-viewed/`          | `POST` | `views.mark_story_viewed`         | Log that story was seen              |
| `/api/story/toggle-like/`          | `POST` | `views.toggle_story_like`         | Like/Unlike a story                  |
| `/api/story/add-reply/`            | `POST` | `views.add_story_reply`           | Send DM reply to a story             |
| `/api/story/repost/`               | `POST` | `views.repost_story`              | Quote story in your own story        |
| `/api/story/<id>/viewers/`         | `GET`  | `views.get_story_viewers`         | See who viewed your story            |

---

## 🤝 9. Social Graph & Requests
| Endpoint                           | Method |             Function              |            Description               |
| :---                               | :---   | :---                              | :---                                 |
| `/api/toggle-follow/`              | `POST` | `views.toggle_follow`             | Follow/Unfollow user                 |
| `/api/follow-states/`              | `POST` | `views.follow_states`             | Batch check follow status            |
| `/api/manage-follow-request/`      | `POST` | `views.manage_follow_request`     | Accept/Decline (Private users)       |
| `/api/toggle-block/`               | `POST` | `views.toggle_block`              | Block/Unblock user                   |
| `/api/toggle-account-privacy/`     | `POST` | `views.toggle_account_privacy`    | Toggle Public/Private                |
| `/api/activity/`                   | `GET`  | `views.get_all_activity`          | Notifications feed                   |
| `/api/manage-chat-acceptance/`     | `POST` | `views.manage_chat_acceptance`    | Accept/Review stranger chat          |

---

## 📥 10. Message Requests (Inbox Filter)
| Endpoint                           | Method |             Function              |            Description               |
| :---                               | :---   | :---                              | :---                                 |
| `/api/dm-requests/`                | `GET`  | `views.get_dm_requests`           | List of requested chats              |
| `/api/dm-requests/count/`          | `GET`  | `views.get_dm_requests_count`     | Number of unread requests            |
| `/api/dm-requests/<id>/check/`     | `GET`  | `views.check_dm_request`          | Check if chat is in Request          |
| `/api/dm-requests/<id>/accept/`    | `POST` | `views.accept_dm_request`         | Move to Main Inbox                   |
| `/api/dm-requests/<id>/decline/`   | `POST` | `views.decline_dm_request`        | Reject chat thread                   |

---

## 📡 11. P2P & Advanced Signaling
| Endpoint                           | Method |             Function              |            Description               |
| :---                               | :---   | :---                              | :---                                 |
| `/api/p2p/send-signal/`            | `POST` | `views.p2p_send_signal`           | WebRTC signaling exchange            |
| `/api/p2p/<id>/signals/`           | `GET`  | `views.p2p_get_signals`           | Poll for signaling data              |
| `/api/p2p/clear-signals/`          | `POST` | `views.p2p_clear_signals`         | Cleanup chat signals                 |
| `/api/p2p/<id>/participants/`      | `GET`  | `views.get_chat_participants_for_p2p`| Identify peer for transfer        |
| `/api/call/notify/`                | `POST` | `views.send_call_notification`    | Trigger call UI on remote            |

---

## 🔍 12. Search & Trends
| Endpoint                           | Method |             Function              |            Description               |
| :---                               | :---   | :---                              | :---                                 |
| `/api/global-search/`              | `GET`  | `views.global_search`             | Global search query `q`              |
| `/api/trending-hashtags/`          | `GET`  | `views.get_trending_hashtags`     | Popular hashtags list                |
| `/api/hashtag/<hashtag>/`          | `GET`  | `views.get_hashtag_scribes`       | Filter posts by tag                  |
| `/api/search-users/`               | `GET`  | `views.search_users_for_mention`  | Search for tagging/mention           |

---

## 🏗️ 13. Groups
| Endpoint                           | Method |             Function              |            Description               |
| :---                               | :---   | :---                              | :---                                 |
| `/api/create-group/`               | `POST` | `views.create_group`              | Create new group chat                |
| `/api/join-group/`                 | `POST` | `views.join_group_api`            | Join group via ID                    |
| `/api/manage-join-request/`        | `POST` | `views.manage_join_request`       | Approve/Reject access                |
| `/api/group/<id>/leave/`           | `POST` | `views.leave_group`               | Exit the group                       |
| `/api/group/<id>/details/`         | `GET`  | `views.get_group_details`         | Full chat manifest                   |

---

## 🌐 14. Support & Internal (Web/Legacy)
| Endpoint                           | Method |             Function              |            Description               |
| :---                               | :---   | :---                              | :---                                 |
| `/explore/`                        | `GET`  | `views.explore`                   | Web HTML template                    |
| `/media/`                          | `GET`  | `views.serve_media_file`          | Media routing logic                  |
| `/post/<post_id>/`                 | `GET`  | `views.view_post`                 | HTML fallback for sharing            |
| `/ (root)`                         | `GET`  | `serve_react`                     | Serve Web front-end                  |
