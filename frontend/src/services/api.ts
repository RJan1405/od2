// Real API service layer - connects to Django backend
import { apiClient } from './apiClient';
import { getMediaUrl } from '@/config/api.config';

export interface User {
  id: string;
  username: string;
  displayName: string;
  avatar: string;
  isOnline: boolean;
  isVerified?: boolean;
  isFollowing?: boolean;
  followersCount?: number;
  followingCount?: number;
  isPrivate?: boolean;
}

export interface Story {
  id: string;
  user: User;
  content: string;
  type: 'image' | 'video' | 'text';
  createdAt: Date;
  viewed: boolean;
  backgroundColor?: string;
  isLiked?: boolean;
  likeCount?: number;
}

// Grouped stories by user (Instagram-style)
export interface UserStories {
  user: User;
  stories: Story[];
  hasUnviewed: boolean;
  storyCount: number;
  isOwn: boolean;
}

export interface Message {
  id: string;
  senderId: string;
  content: string;
  type: 'text' | 'image' | 'video' | 'file' | 'audio' | 'document';
  timestamp: Date;
  isOneTimeView?: boolean;
  consumed?: boolean;
  viewed?: boolean;
  mediaUrl?: string;
  mediaFilename?: string;
  isOwn?: boolean;
  replyTo?: string; // ID of the message being replied to
  replyToContent?: string; // Content of the message being replied to
  replyToSender?: string; // Sender name of the message being replied to
  storyReply?: {
    story_id: number;
    story_type: 'text' | 'image' | 'video';
    story_content?: string;
    story_media_url?: string;
    story_owner: string;
  };
  sharedScribe?: {
    id: string;
    content: string;
    image?: string;
    user: {
      username: string;
      avatar: string;
    };
  };
  sharedOmzo?: {
    id: string;
    caption: string;
    videoUrl: string;
    user: {
      username: string;
      avatar: string;
    };
  };
}

export interface Chat {
  id: string;
  user: User;
  lastMessage: string;
  timestamp: Date;
  unreadCount: number;
  isPrivate: boolean;
  isNewRequest?: boolean;
  chat_type?: 'private' | 'group';
  name?: string;
  participants?: User[];
  groupAvatar?: string;
}

export interface Scribe {
  id: string;
  user: User;
  content: string;
  type: 'text' | 'image' | 'video' | 'html';
  htmlContent?: string;
  mediaUrl?: string;
  likes: number;
  dislikes: number;
  comments: number;
  reposts: number;
  createdAt: Date;
  isLiked?: boolean;
  isDisliked?: boolean;
  isSaved?: boolean;
  // Optional flag if backend starts returning whether current user has reposted
  isReposted?: boolean;
  // Feed discriminator (added by explore feed API)
  feedType?: 'scribe' | 'omzo';
  // Repost fields
  isRepost?: boolean;
  originalType?: 'scribe' | 'omzo' | 'story';
  originalData?: {
    id: string;
    user: User;
    content?: string;
    caption?: string;
    type?: string;
    mediaUrl?: string;
    videoUrl?: string;
    likes: number;
    comments: number;
    reposts?: number;
    views?: number;
    timestamp: Date;
  };
}

export interface Repost {
  id: string;
  user: User; // who reposted
  original: Scribe; // the original scribe that was reposted
  repostedAt: Date;
}

export interface Omzo {
  id: string;
  user: User;
  videoUrl: string;
  caption: string;
  audioName: string;
  likes: number;
  dislikes: number;
  shares: number;
  views: number;
  comments: number;
  reposts: number;
  createdAt: Date;
  isLiked?: boolean;
  isDisliked?: boolean;
  isSaved?: boolean;
  isReposted?: boolean;
}

export interface Notification {
  id: string;
  type: 'like' | 'comment' | 'repost' | 'mention' | 'connection_request' | 'follow' | 'reply' | 'omzo_like' | 'omzo_comment' | 'post_report' | 'omzo_report';
  user: User;
  content: string;
  timestamp: Date;
  read: boolean;
  scribeId?: string;
  omzoId?: string;
  previewImage?: string;
}

// Mock data generators
// Current user (your profile)
export const currentUser: User = {
  id: 'me',
  username: 'odnix_user',
  displayName: 'You',
  avatar: 'https://i.pravatar.cc/150?img=70',
  isOnline: true,
  isVerified: true,
};

export const mockUsers: User[] = [
  currentUser,
  { id: '1', username: 'alex_tech', displayName: 'Alex Turner', avatar: 'https://i.pravatar.cc/150?img=1', isOnline: true, isVerified: true },
  { id: '2', username: 'sarah_designs', displayName: 'Sarah Chen', avatar: 'https://i.pravatar.cc/150?img=2', isOnline: true },
  { id: '3', username: 'mike_music', displayName: 'Mike Johnson', avatar: 'https://i.pravatar.cc/150?img=3', isOnline: false },
  { id: '4', username: 'emma_art', displayName: 'Emma Wilson', avatar: 'https://i.pravatar.cc/150?img=4', isOnline: true, isVerified: true },
  { id: '5', username: 'david_dev', displayName: 'David Park', avatar: 'https://i.pravatar.cc/150?img=5', isOnline: false },
  { id: '6', username: 'lisa_photo', displayName: 'Lisa Brown', avatar: 'https://i.pravatar.cc/150?img=6', isOnline: true },
  { id: '7', username: 'james_fit', displayName: 'James Miller', avatar: 'https://i.pravatar.cc/150?img=7', isOnline: false },
  { id: '8', username: 'nina_travel', displayName: 'Nina Garcia', avatar: 'https://i.pravatar.cc/150?img=8', isOnline: true },
];

export const mockStories: Story[] = mockUsers.slice(0, 6).map((user, i) => ({
  id: `story-${i}`,
  user,
  content: `https://picsum.photos/seed/${i}/400/600`,
  type: 'image',
  createdAt: new Date(Date.now() - i * 3600000),
  viewed: i > 2,
}));

export const mockChats: Chat[] = [
  { id: '1', user: mockUsers[0], lastMessage: 'Hey! Check out my new project 🚀', timestamp: new Date(Date.now() - 300000), unreadCount: 2, isPrivate: false },
  { id: '2', user: mockUsers[1], lastMessage: 'The design looks amazing!', timestamp: new Date(Date.now() - 900000), unreadCount: 0, isPrivate: true },
  { id: '3', user: mockUsers[2], lastMessage: 'Can we collaborate on this?', timestamp: new Date(Date.now() - 3600000), unreadCount: 1, isPrivate: false },
  { id: '4', user: mockUsers[3], lastMessage: 'Thanks for the feedback! 💜', timestamp: new Date(Date.now() - 7200000), unreadCount: 0, isPrivate: true },
  { id: '5', user: mockUsers[4], lastMessage: 'Let me know when you are free', timestamp: new Date(Date.now() - 14400000), unreadCount: 0, isPrivate: false, isNewRequest: true },
  { id: '6', user: mockUsers[5], lastMessage: 'Those photos are incredible', timestamp: new Date(Date.now() - 28800000), unreadCount: 0, isPrivate: false },
];

export const mockMessages: Message[] = [
  { id: '1', senderId: '1', content: 'Hey! How are you doing?', type: 'text', timestamp: new Date(Date.now() - 3600000) },
  { id: '2', senderId: 'me', content: 'I am great! Working on something cool', type: 'text', timestamp: new Date(Date.now() - 3500000) },
  { id: '3', senderId: '1', content: 'https://picsum.photos/seed/chat1/400/300', type: 'image', timestamp: new Date(Date.now() - 3400000) },
  { id: '4', senderId: 'me', content: 'Wow that looks amazing! 🔥', type: 'text', timestamp: new Date(Date.now() - 3300000) },
  { id: '5', senderId: '1', content: 'Thanks! I spent hours on it', type: 'text', timestamp: new Date(Date.now() - 3200000) },
  { id: '6', senderId: 'me', content: 'It really shows. The attention to detail is incredible', type: 'text', timestamp: new Date(Date.now() - 600000) },
  { id: '7', senderId: '1', content: 'Hey! Check out my new project 🚀', type: 'text', timestamp: new Date(Date.now() - 300000) },
];

export const mockScribes: Scribe[] = [
  {
    id: '1',
    user: mockUsers[0],
    content: 'Just shipped a new feature! The future of social is here. What do you all think? 🚀✨',
    type: 'text',
    likes: 234,
    dislikes: 5,
    comments: 45,
    reposts: 12,
    createdAt: new Date(Date.now() - 1800000),
  },
  {
    id: '2',
    user: mockUsers[1],
    content: 'New design exploration',
    type: 'image',
    mediaUrl: 'https://picsum.photos/seed/scribe1/600/400',
    likes: 567,
    dislikes: 8,
    comments: 89,
    reposts: 34,
    createdAt: new Date(Date.now() - 3600000),
    isLiked: true,
  },
  {
    id: '3',
    user: mockUsers[3],
    content: 'Interactive art piece',
    type: 'html',
    htmlContent: `
      <div style="width:100%;height:200px;background:linear-gradient(45deg,#ff006e,#8338ec,#3a86ff);display:flex;align-items:center;justify-content:center;">
        <h2 style="color:white;font-size:24px;font-weight:bold;text-shadow:0 2px 10px rgba(0,0,0,0.3);">Interactive Canvas</h2>
      </div>
    `,
    likes: 890,
    dislikes: 12,
    comments: 156,
    reposts: 67,
    createdAt: new Date(Date.now() - 7200000),
  },
  {
    id: '4',
    user: mockUsers[5],
    content: 'Golden hour magic ✨',
    type: 'image',
    mediaUrl: 'https://picsum.photos/seed/scribe2/600/800',
    likes: 1234,
    dislikes: 15,
    comments: 234,
    reposts: 89,
    createdAt: new Date(Date.now() - 14400000),
    isSaved: true,
  },
];

export const mockReposts: Repost[] = [
  {
    id: 'r1',
    user: mockUsers[1],
    original: mockScribes[3],
    repostedAt: new Date(Date.now() - 2000000),
  },
  {
    id: 'r2',
    user: mockUsers[3],
    original: mockScribes[1],
    repostedAt: new Date(Date.now() - 8000000),
  },
  {
    id: 'r3',
    user: mockUsers[0],
    original: mockScribes[2],
    repostedAt: new Date(Date.now() - 500000),
  },
];

export const mockOmzos: Omzo[] = [
  {
    id: '1',
    user: mockUsers[0],
    videoUrl: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4',
    caption: 'The future is now 🚀 #tech #innovation',
    audioName: 'Original Sound - alex_tech',
    likes: 12500,
    dislikes: 120,
    shares: 890,
    views: 50000,
    comments: 145,
    reposts: 0,
    createdAt: new Date(Date.now() - 3600000),
  },
  {
    id: '2',
    user: mockUsers[1],
    videoUrl: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4',
    caption: 'Design process behind the scenes ✨ #design #creative',
    audioName: 'Trending Sound - Viral Mix',
    likes: 45000,
    dislikes: 230,
    shares: 2300,
    views: 150000,
    comments: 450,
    reposts: 0,
    createdAt: new Date(Date.now() - 7200000),
    isLiked: true,
  },
  {
    id: '3',
    user: mockUsers[3],
    videoUrl: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4',
    caption: 'Art in motion 🎨 #art #digital',
    audioName: 'Chill Vibes - Lo-Fi Beats',
    likes: 78000,
    dislikes: 450,
    shares: 5600,
    views: 300000,
    comments: 890,
    reposts: 0,
    createdAt: new Date(Date.now() - 14400000),
  },
];

export const mockNotifications: Notification[] = [
  { id: '1', type: 'like', user: mockUsers[1], content: 'liked your scribe', timestamp: new Date(Date.now() - 300000), read: false },
  { id: '2', type: 'comment', user: mockUsers[2], content: 'commented: "This is amazing!"', timestamp: new Date(Date.now() - 900000), read: false },
  { id: '3', type: 'connection_request', user: mockUsers[4], content: 'wants to connect with you', timestamp: new Date(Date.now() - 1800000), read: false },
  { id: '4', type: 'repost', user: mockUsers[5], content: 'reposted your scribe', timestamp: new Date(Date.now() - 3600000), read: true },
  { id: '5', type: 'mention', user: mockUsers[6], content: 'mentioned you in a scribe', timestamp: new Date(Date.now() - 7200000), read: true },
];

// Real API functions - Connect to Django backend
export const api = {
  // Stories
  getStories: async (): Promise<Story[]> => {
    try {
      // Use the new following-stories endpoint to get stories from followed users
      const response = await apiClient.get<any>('/api/following-stories/');
      const usersWithStories = response.users_with_stories || [];

      // Flatten the grouped stories into a single array for the UI
      const allStories: Story[] = [];

      for (const userGroup of usersWithStories) {
        const user = userGroup.user;
        const stories = userGroup.stories || [];

        for (const s of stories) {
          allStories.push({
            id: s.id?.toString(),
            user: {
              id: user.id?.toString(),
              username: user.username || '',
              displayName: user.full_name || user.username || '',
              avatar: getMediaUrl(user.profile_picture_url || ''),
              isOnline: false,
              isVerified: user.is_verified || false,
            },
            content: (s.story_type === 'text') ? (s.content || '') : getMediaUrl(s.media_url || ''),
            type: (s.story_type || 'image') as 'image' | 'video' | 'text',
            createdAt: new Date(s.created_at || Date.now()),
            viewed: s.is_viewed || false,
            backgroundColor: s.background_color || '#000000',
            isLiked: s.is_liked || false,
            likeCount: s.like_count || 0,
          });
        }
      }

      return allStories;
    } catch (error) {
      console.error('Error fetching stories:', error);
      return [];
    }
  },

  // Get stories grouped by user (Instagram-style - one circle per user)
  getGroupedStories: async (): Promise<UserStories[]> => {
    try {
      const response = await apiClient.get<any>('/api/following-stories/');
      const usersWithStories = response.users_with_stories || [];

      return usersWithStories.map((userGroup: any) => {
        const user = userGroup.user;
        const stories = userGroup.stories || [];

        return {
          user: {
            id: user.id?.toString(),
            username: user.username || '',
            displayName: user.full_name || user.username || '',
            avatar: getMediaUrl(user.profile_picture_url || ''),
            isOnline: false,
            isVerified: user.is_verified || false,
          },
          stories: stories.map((s: any) => ({
            id: s.id?.toString(),
            user: {
              id: user.id?.toString(),
              username: user.username || '',
              displayName: user.full_name || user.username || '',
              avatar: getMediaUrl(user.profile_picture_url || ''),
              isOnline: false,
              isVerified: user.is_verified || false,
            },
            content: (s.story_type === 'text') ? (s.content || '') : getMediaUrl(s.media_url || ''),
            type: (s.story_type || 'image') as 'image' | 'video' | 'text',
            createdAt: new Date(s.created_at || Date.now()),
            viewed: s.is_viewed || false,
            backgroundColor: s.background_color || '#000000',
            isLiked: s.is_liked || false,
            likeCount: s.like_count || 0,
          })),
          hasUnviewed: userGroup.has_unviewed || false,
          storyCount: userGroup.story_count || stories.length,
          isOwn: userGroup.is_own || false,
        };
      });
    } catch (error) {
      console.error('Error fetching grouped stories:', error);
      return [];
    }
  },

  // Story interactions
  toggleStoryLike: async (storyId: string): Promise<{ success: boolean; is_liked: boolean; like_count: number; error?: string }> => {
    try {
      const response = await apiClient.post<any>('/api/story/toggle-like/', {
        story_id: storyId
      });
      return {
        success: response.success || false,
        is_liked: response.is_liked || false,
        like_count: response.like_count || 0,
        error: response.error
      };
    } catch (error) {
      console.error('Error toggling story like:', error);
      return { success: false, is_liked: false, like_count: 0, error: String(error) };
    }
  },

  replyToStory: async (storyId: string, content: string): Promise<{ success: boolean; error?: string; message_error?: string }> => {
    try {
      const response = await apiClient.post<any>('/api/story/add-reply/', {
        story_id: storyId,
        content: content
      });
      return { success: response.success || false, error: response.error, message_error: response.message_error };
    } catch (error) {
      console.error('Error replying to story:', error);
      return { success: false, error: String(error) };
    }
  },

  repostStory: async (storyId: string): Promise<{ success: boolean; error?: string }> => {
    try {
      const response = await apiClient.post<any>('/api/story/repost/', {
        story_id: storyId
      });
      return { success: response.success || false, error: response.error };
    } catch (error) {
      console.error('Error reposting story:', error);
      return { success: false, error: String(error) };
    }
  },

  // Chats
  getChats: async (): Promise<Chat[]> => {
    try {
      const response = await apiClient.get<any>('/api/chats/');
      const chats = response.chats || response || [];
      console.log('DEBUG: Raw chats from API:', JSON.stringify(chats, null, 2));

      const transformedChats = chats.map((c: any) => {
        const isGroup = c.chat_type === 'group' || c.is_group;
        const chat = {
          id: c.id?.toString() || c.chat_id?.toString(),
          user: {
            id: c.other_user?.id?.toString() || c.user_id?.toString() || (isGroup ? 'group' : ''),
            username: c.other_user?.username || c.username || (isGroup ? 'Group' : 'Unknown'),
            displayName: c.other_user?.full_name || c.other_user?.username || c.display_name || c.name || (isGroup ? c.name : 'Unknown User'),
            avatar: getMediaUrl(c.other_user?.profile_picture || c.avatar || ''),
            isOnline: c.other_user?.is_online || false,
            isVerified: c.other_user?.is_verified || false,
          },
          lastMessage: c.last_message?.content || c.last_message || '',
          timestamp: new Date(c.last_message_time || c.timestamp || Date.now()),
          unreadCount: c.unread_count || 0,
          isPrivate: c.is_private !== undefined ? c.is_private : !isGroup,
          isNewRequest: c.is_new_request || false,
          chat_type: c.chat_type || (isGroup ? 'group' : 'private'),
          name: c.name,
          groupAvatar: getMediaUrl(c.group_avatar || c.avatar || '')
        };
        // console.log(`DEBUG: Chat ${chat.id} - displayName: "${chat.user.displayName}"`);
        return chat;
      });

      console.log('DEBUG: Transformed chats:', transformedChats);
      return transformedChats;
    } catch (error) {
      console.error('Error fetching chats:', error);
      return [];
    }
  },

  // Create or Get Chat
  createChat: async (username: string): Promise<string | null> => {
    try {
      const response = await apiClient.post<any>('/api/create-chat/', { username });
      if (response.success && response.chat_id) {
        return response.chat_id.toString();
      }
      return null;
    } catch (error) {
      console.error('Error creating chat:', error);
      return null;
    }
  },

  // Messages
  getMessages: async (chatId: string): Promise<Message[]> => {
    try {
      const response = await apiClient.get<any>(`/api/chat/${chatId}/messages/`);
      const messages = response.messages || response || [];
      return messages.map((m: any) => ({
        id: m.id?.toString() || m.message_id?.toString(),
        senderId: m.sender?.id?.toString() || m.sender_id?.toString() || '',
        content: m.content || m.text || '',
        type: (m.media_type || m.file_type || m.message_type || m.type || 'text') as 'text' | 'image' | 'video' | 'file' | 'audio' | 'document',
        timestamp: new Date(m.timestamp_iso || m.created_at || m.timestamp || Date.now()),
        mediaUrl: m.file || m.media_url,
        mediaFilename: m.media_filename || m.filename,
        isOwn: m.is_own || false,
        viewed: m.is_read || false,
        replyTo: m.reply_to?.id?.toString(),
        replyToContent: m.reply_to?.content,
        replyToSender: m.reply_to?.sender_name,
        storyReply: m.story_reply,
        sharedScribe: m.shared_scribe,
        sharedOmzo: m.shared_omzo,
        isOneTimeView: m.one_time || false,
        consumed: m.consumed || false,
      }));
    } catch (error) {
      console.error('Error fetching messages:', error);
      return [];
    }
  },

  // Send Message
  sendMessage: async (chatId: string, content: string, file?: File, replyToId?: string, isOneTimeView?: boolean, sharedScribeId?: string, sharedOmzoId?: string): Promise<Message | null> => {
    try {
      const formData = new FormData();
      formData.append('chat_id', chatId);
      if (content) formData.append('content', content);
      if (file) formData.append('media', file);
      if (replyToId) formData.append('reply_to', replyToId);
      if (isOneTimeView) formData.append('one_time', 'true');
      if (sharedScribeId) formData.append('shared_scribe_id', sharedScribeId);
      if (sharedOmzoId) formData.append('shared_omzo_id', sharedOmzoId);

      const response = await apiClient.post<any>('/api/send-message/', formData);
      // Access message directly as ApiClient returns the parsed JSON
      const m = response.message || response.data?.message;

      if (!m) {
        if (response.error) throw new Error(response.error);
        return null;
      }

      return {
        id: m.id?.toString(),
        senderId: m.sender_id?.toString(),
        content: m.content,
        type: m.media_type || m.message_type || 'text',
        timestamp: new Date(m.timestamp_iso || m.timestamp),
        isOneTimeView: m.one_time,
        viewed: m.is_read || false,
        mediaUrl: m.media_url,
        mediaFilename: m.media_filename,
        isOwn: m.is_own,
        replyTo: m.reply_to?.id,
        replyToContent: m.reply_to?.content,
        replyToSender: m.reply_to?.sender_name,
        sharedScribe: m.shared_scribe,
        sharedOmzo: m.shared_omzo,
        consumed: m.consumed || false
      } as Message;
    } catch (error) {
      console.error('Error sending message:', error);
      return null;
    }
  },

  // Consume One-Time Message
  consumeOneTimeMessage: async (messageId: string): Promise<{ success: boolean; content?: string; media_url?: string; media_type?: string; } | null> => {
    try {
      const response = await apiClient.post<any>(`/api/consume-message/${messageId}/`);
      // ApiClient returns the JSON object directly
      if (response.success) {
        return response;
      }
      return null;
    } catch (error) {
      console.error('Error consuming message:', error);
      return null;
    }
  },

  // Get Chat Details
  getChatDetails: async (chatId: string): Promise<Chat | null> => {
    try {
      const response = await apiClient.get<any>(`/api/chat/${chatId}/details/`);
      const c = response.chat;
      if (!c) return null;

      const isGroup = c.is_group || c.type === 'group';

      // For group chat, we might not have 'other_user'. using a placeholder or first participant.
      const otherUser = c.other_user || (c.participants && c.participants.length > 0 ? c.participants[0] : null);

      return {
        id: c.id?.toString(),
        user: {
          id: otherUser?.id?.toString() || 'group',
          username: otherUser?.username || 'Group',
          displayName: otherUser?.full_name || otherUser?.first_name || otherUser?.username || c.name || 'Group Chat',
          avatar: getMediaUrl(otherUser?.profile_picture || otherUser?.avatar || c.avatar || ''),
          isOnline: otherUser?.is_online || false,
          isVerified: otherUser?.is_verified || false,
        },
        lastMessage: '',
        timestamp: new Date(),
        unreadCount: 0,
        isPrivate: !isGroup,
        isNewRequest: false,
        chat_type: isGroup ? 'group' : 'private',
        name: c.name,
        participants: c.participants ? c.participants.map((p: any) => ({
          id: p.id.toString(),
          username: p.username,
          displayName: p.full_name || p.username,
          avatar: getMediaUrl(p.profile_picture || ''),
          isOnline: p.is_online,
          isVerified: p.is_verified || false
        })) : [],
        groupAvatar: getMediaUrl(c.avatar || '')
      };
    } catch (error) {
      console.error('Error fetching chat details:', error);
      return null;
    }
  },

  // Scribes (Posts)
  getScribes: async (): Promise<Scribe[]> => {
    try {
      const response = await apiClient.get<any>('/dashboard/'); // Note: Dashboard returns full context, explore-feed is preferred for explore
      const scribes = response.scribes_data || response.scribes || []; // Adapted for dashboard response structure
      return scribes.map((s: any) => ({
        id: s.id?.toString() || s.scribe_id?.toString(),
        user: {
          id: s.user?.id?.toString() || s.user_id?.toString(),
          username: s.user?.username || s.username || '',
          displayName: s.user?.full_name || s.user?.username || s.display_name || '',
          avatar: getMediaUrl(s.user?.profile_picture || s.avatar || ''),
          isOnline: s.user?.is_online || false,
          isVerified: s.user?.is_verified || false,
        },
        content: s.content || s.text || '',
        type: (s.media_type || s.type || s.content_type || 'text') as 'text' | 'image' | 'video' | 'html',
        mediaUrl: getMediaUrl(s.media || s.image_url || s.media_url || ''),
        htmlContent: s.html_content,
        likes: s.like_count || s.likes || 0,
        dislikes: s.dislike_count || s.dislikes || 0,
        comments: s.comment_count || s.comments || 0,
        reposts: s.repost_count || s.reposts || 0,
        createdAt: new Date(s.created_at || s.timestamp || Date.now()),
        isLiked: s.is_liked || false,
        isDisliked: s.is_disliked || false,
        isSaved: s.is_saved || false,
        isReposted: s.is_reposted || false,
      }));
    } catch (error) {
      console.error('Error fetching scribes:', error);
      return [];
    }
  },

  // Explore Feed (Mixed)
  getExploreFeed: async (page = 1): Promise<(Scribe | Omzo)[]> => {
    try {
      const response = await apiClient.get<any>(`/api/explore-feed/?page=${page}`);
      const results = response.results || [];

      return results.map((item: any) => {
        const user = {
          id: item.user?.id?.toString() || '',
          username: item.user?.username || '',
          displayName: item.user?.displayName || item.user?.username || '',
          avatar: getMediaUrl(item.user?.avatar || ''),
          isOnline: false,
          isVerified: item.user?.isVerified || false,
        };

        if (item.type === 'omzo') {
          return {
            id: item.id?.toString(),
            user,
            // Map to Omzo interface
            videoUrl: getMediaUrl(item.videoUrl || ''),
            caption: item.caption || '',
            audioName: 'Original Sound',
            likes: item.likes || 0,
            dislikes: item.dislikes || 0,
            shares: item.shares || 0,
            reposts: item.reposts || 0,
            views: item.views || item.view_count || 0,
            comments: item.comments || item.comment_count || 0,
            createdAt: new Date(item.createdAt || Date.now()),
            isLiked: item.isLiked || false,
            isDisliked: item.isDisliked || false,
            isSaved: item.isSaved || false,
            isReposted: item.isReposted || false,
            // Add type discriminator for frontend to distinguish
            feedType: 'omzo'
          } as any; // Cast to avoid strict union issues for now, caller handles it
        } else {
          // Scribe
          return {
            id: item.id?.toString(),
            user,
            content: item.content || '',
            type: (item.scribeType === 'code_scribe' || item.type === 'code_scribe' || item.scribeType === 'html') ? 'html' : ((item.scribeType || item.type || 'text') as 'text' | 'image' | 'video' | 'html'),
            mediaUrl: getMediaUrl(item.mediaUrl || ''),
            likes: item.likes || 0,
            dislikes: item.dislikes || 0,
            comments: item.comments || 0,
            reposts: item.reposts || 0,
            createdAt: new Date(item.createdAt || Date.now()),
            isLiked: item.isLiked || false,
            isDisliked: item.isDisliked || false,
            isSaved: item.isSaved || false,
            isReposted: item.isReposted || false,
            feedType: 'scribe',
            // Construct HTML content if present
            htmlContent: (item.scribeType === 'code_scribe' || item.type === 'code_scribe' || item.scribeType === 'html') && (item.code_html || item.code_css || item.code_js) ? `
                <!DOCTYPE html>
                <html>
                <head>
                  <style>
                    body { margin: 0; overflow: hidden; }
                    ${item.code_css || ''}
                  </style>
                </head>
                <body>
                  ${item.code_html || ''}
                  <script>
                    ${item.code_js || ''}
                  </script>
                </body>
                </html>
             ` : undefined
          } as any;
        }
      });
    } catch (error) {
      console.error('Error fetching explore feed:', error);
      return [];
    }
  },

  // Omzos (Videos)
  getOmzos: async (): Promise<Omzo[]> => {
    try {
      const response = await apiClient.get<any>('/api/omzo/batch/');
      const omzos = response.omzos || response.data || response || [];
      return omzos.map((o: any) => ({
        id: o.id?.toString() || o.omzo_id?.toString(),
        user: {
          id: o.user_id?.toString() || o.user?.id?.toString() || '0',
          username: o.username || o.user?.username || '',
          displayName: o.display_name || o.username || o.user?.full_name || o.username || '',
          avatar: getMediaUrl(o.user_avatar || o.avatar || o.user?.profile_picture || ''),
          isOnline: o.is_online || o.user?.is_online || false,
          isVerified: o.is_verified || o.user?.is_verified || false,
        },
        videoUrl: getMediaUrl(o.video_url || o.url || o.video || ''),
        caption: o.caption || '',
        audioName: o.audio_name || 'Original Sound',
        likes: o.likes || o.likes_count || 0,
        dislikes: o.dislikes || o.dislikes_count || 0,
        views: o.views || o.views_count || 0,
        comments: o.comments || o.comments_count || 0,
        shares: o.shares || o.shares_count || 0,
        reposts: o.reposts || o.repost_count || 0,
        createdAt: new Date(o.created_at || o.timestamp || Date.now()),
        isLiked: o.is_liked || false,
        isDisliked: o.is_disliked || false,
        isReposted: o.is_reposted || false,
      }));
    } catch (error) {
      console.error('Error fetching omzos:', error);
      return [];
    }
  },

  // Notifications
  trackOmzoView: async (omzoId: string): Promise<void> => {
    try {
      await apiClient.post('/api/omzo/track-view/', { omzo_id: omzoId });
    } catch (error) {
      console.error('Error tracking omzo view:', error);
    }
  },

  getNotifications: async (): Promise<Notification[]> => {
    try {
      const response = await apiClient.get<any>('/api/activity/');
      const activities = response.activity_items || [];

      return activities.map((item: any) => {
        let type: Notification['type'] = 'like'; // default
        let content = '';
        let scribeId = undefined;
        let omzoId = undefined;
        let commentId = undefined;
        let previewImage = undefined;

        if (item.type === 'like') {
          type = 'like';
          content = 'liked your scribe';
          scribeId = item.scribe?.id?.toString();
        } else if (item.type === 'comment') {
          type = 'comment';
          content = `commented: "${item.comment_content || ''}"`;
          scribeId = item.scribe?.id?.toString();
          commentId = item.comment_id?.toString();
        } else if (item.type === 'follow') {
          type = 'follow'; // map to connection_request or new type
          content = 'started following you';
        } else if (item.type === 'repost') {
          type = 'repost';
          content = 'reposted your scribe';
          scribeId = item.scribe?.id?.toString();
        } else if (item.type === 'mention') {
          type = 'mention';
          content = 'mentioned you in a scribe';
          scribeId = item.scribe?.id?.toString();
        } else if (item.type === 'omzo_like') {
          type = 'omzo_like';
          content = 'liked your omzo';
          omzoId = item.omzo?.id?.toString();
        } else if (item.type === 'omzo_comment') {
          type = 'omzo_comment';
          content = `commented on your omzo: "${item.comment_content || ''}"`;
          omzoId = item.omzo?.id?.toString();
          commentId = item.comment_id?.toString();
        } else if (item.type === 'post_report') {
          type = 'post_report';
          content = `reported your post for ${item.reason || 'violation'}`;
          scribeId = item.scribe?.id?.toString();
        } else if (item.type === 'omzo_report') {
          type = 'omzo_report';
          content = `reported your omzo for ${item.reason || 'violation'}`;
          omzoId = item.omzo?.id?.toString();
        }

        return {
          id: `${item.type}-${item.timestamp}`, // unique key if no ID
          type,
          user: {
            id: item.user.id?.toString(),
            username: item.user.username,
            displayName: item.user.full_name || item.user.username,
            avatar: getMediaUrl(item.user.profile_picture_url || ''),
            isOnline: false,
            isVerified: false
          },
          content,
          timestamp: new Date(item.timestamp),
          read: item.is_read || false, // Use backend's is_read field if available
          scribeId,
          omzoId,
          commentId
        };
      });

    } catch (error) {
      console.error('Error fetching notifications:', error);
      return [];
    }
  },

  // Search Users
  searchUsers: async (query: string): Promise<User[]> => {
    try {
      const response = await apiClient.get<any>(`/api/search-users/?q=${encodeURIComponent(query)}`);
      const users = response.users || response || [];
      return users.map((u: any) => ({
        id: u.id?.toString() || u.user_id?.toString(),
        username: u.username || '',
        displayName: u.full_name || u.username || u.display_name || '',
        avatar: getMediaUrl(u.profile_picture || u.avatar || ''),
        isOnline: u.is_online || false,
        isVerified: u.is_verified || false,
        isFollowing: u.is_following || false,
      }));
    } catch (error) {
      console.error('Error searching users:', error);
      return [];
    }
  },

  // Toggle Follow
  toggleFollow: async (username: string): Promise<{ success: boolean; isFollowing: boolean }> => {
    try {
      const response = await apiClient.post<any>('/api/toggle-follow/', { username });
      return {
        success: response.success,
        isFollowing: response.is_following
      };
    } catch (error) {
      console.error('Error toggling follow:', error);
      // Return previous state or error? Assuming caller handles simple toggle/error
      throw error;
    }
  },

  // Omzo Actions
  toggleOmzoLike: async (omzoId: string): Promise<{ success: boolean; isLiked: boolean; likesCount: number }> => {
    try {
      const response = await apiClient.post<any>('/api/omzo/like/', { omzo_id: omzoId });
      return {
        success: response.success,
        isLiked: response.is_liked,
        likesCount: response.like_count
      };
    } catch (error) {
      console.error('Error toggling omzo like:', error);
      throw error;
    }
  },

  toggleOmzoDislike: async (omzoId: string): Promise<{ success: boolean; isDisliked: boolean; likesCount: number }> => {
    try {
      const response = await apiClient.post<any>('/api/omzo/dislike/', { omzo_id: omzoId });
      return {
        success: response.success,
        isDisliked: response.is_disliked,
        likesCount: response.like_count
      };
    } catch (error) {
      console.error('Error toggling omzo dislike:', error);
      throw error;
    }
  },

  // Save/Unsave Actions
  toggleSaveScribe: async (scribeId: string): Promise<{ success: boolean; isSaved: boolean }> => {
    try {
      const response = await apiClient.post<any>('/api/save-scribe/', { scribe_id: scribeId });
      return {
        success: response.success,
        isSaved: response.is_saved
      };
    } catch (error) {
      console.error('Error toggling scribe save:', error);
      throw error;
    }
  },

  toggleSaveOmzo: async (omzoId: string): Promise<{ success: boolean; isSaved: boolean }> => {
    try {
      const response = await apiClient.post<any>('/api/save-omzo/', { omzo_id: omzoId });
      return {
        success: response.success,
        isSaved: response.is_saved
      };
    } catch (error) {
      console.error('Error toggling omzo save:', error);
      throw error;
    }
  },

  getSavedItems: async (): Promise<any[]> => {
    try {
      const response = await apiClient.get<any>('/api/saved-items/');
      const items = response.saved_items || [];

      return items.map((item: any) => {
        const user = {
          id: item.user.id.toString(),
          username: item.user.username,
          displayName: item.user.full_name || item.user.username,
          avatar: getMediaUrl(item.user.profile_picture_url || ''),
          isOnline: false,
          isVerified: item.user.is_verified || false,
        };

        if (item.type === 'omzo') {
          return {
            id: item.id.toString(),
            user,
            videoUrl: getMediaUrl(item.video_url || ''),
            caption: item.caption || '',
            likes: item.likes || 0,
            dislikes: item.dislikes || 0,
            views: item.views || 0,
            comments: item.comments || 0,
            shares: item.shares || 0,
            createdAt: new Date(item.created_at || Date.now()),
            isLiked: false,
            isSaved: true,
            feedType: 'omzo'
          };
        } else {
          return {
            id: item.id.toString(),
            user,
            content: item.content || '',
            type: (item.media_type || 'text') as 'text' | 'image' | 'video' | 'html',
            mediaUrl: getMediaUrl(item.image_url || ''),
            likes: item.likes || 0,
            dislikes: item.dislikes || 0,
            comments: item.comments || 0,
            reposts: item.reposts || 0,
            createdAt: new Date(item.created_at || Date.now()),
            isLiked: false,
            isSaved: true,
            feedType: 'scribe'
          };
        }
      });
    } catch (error) {
      console.error('Error fetching saved items:', error);
      return [];
    }
  },


  // Scribe Actions
  toggleLike: async (scribeId: string): Promise<{ success: boolean; isLiked: boolean; likesCount: number }> => {
    try {
      const response = await apiClient.post<any>('/api/toggle-like/', { scribe_id: scribeId });
      return {
        success: response.success,
        isLiked: response.is_liked,
        likesCount: response.like_count // Use like_count from backend
      };
    } catch (error) {
      console.error('Error toggling like:', error);
      throw error;
    }
  },

  toggleDislike: async (scribeId: string): Promise<{ success: boolean; isDisliked: boolean; likesCount: number }> => {
    try {
      const response = await apiClient.post<any>('/api/toggle-dislike/', { scribe_id: scribeId });
      return {
        success: response.success,
        isDisliked: response.is_disliked, // Backend might return is_disliked?
        likesCount: response.like_count // Assuming consistency
      };
    } catch (error) {
      console.error('Error toggling dislike:', error);
      throw error;
    }
  },

  toggleRepostScribe: async (scribeId: string): Promise<{ success: boolean; isReposted: boolean }> => {
    try {
      console.log('[API] toggleRepostScribe called with ID:', scribeId, 'Type:', typeof scribeId);
      const payload = {
        type: 'scribe',
        id: parseInt(scribeId), // Ensure ID is a number
      };
      console.log('[API] Sending payload:', payload);

      const response = await apiClient.post<any>('/api/repost/', payload);
      console.log('[API] Response received:', response);

      return {
        success: !!response?.success,
        isReposted: !!(response?.is_reposted ?? response?.isReposted),
      };
    } catch (error) {
      console.error('[API] Error toggling repost:', error);
      throw error;
    }
  },

  toggleRepostOmzo: async (omzoId: string): Promise<{ success: boolean; isReposted: boolean }> => {
    try {
      console.log('[API] toggleRepostOmzo called with ID:', omzoId, 'Type:', typeof omzoId);
      const payload = {
        type: 'omzo',
        id: parseInt(omzoId), // Ensure ID is a number
      };
      console.log('[API] Sending payload:', payload);

      const response = await apiClient.post<any>('/api/repost/', payload);
      console.log('[API] Response received:', response);

      return {
        success: !!response?.success,
        isReposted: !!(response?.is_reposted ?? response?.isReposted),
      };
    } catch (error) {
      console.error('[API] Error toggling omzo repost:', error);
      throw error;
    }
  },

  getOmzoComments: async (omzoId: string): Promise<any[]> => {
    try {
      const response = await apiClient.get<any>(`/api/omzo/${omzoId}/comments/`);
      const comments = response.comments || [];
      return comments.map((c: any) => ({
        id: c.id?.toString(),
        userId: c.user?.id?.toString(),
        username: c.user?.username,
        avatar: getMediaUrl(c.user?.avatar || c.user?.profile_picture_url || ''),
        text: c.content,
        createdAt: c.created_at || c.timestamp
      }));
    } catch (error) {
      console.error('Error fetching omzo comments:', error);
      return [];
    }
  },

  addOmzoComment: async (omzoId: string, content: string): Promise<any | null> => {
    try {
      const response = await apiClient.post<any>('/api/omzo/comment/', { omzo_id: omzoId, content });
      if (response.success) {
        const c = response.comment;
        const username = c.user?.username || 'User';
        const avatarUrl = c.user?.profile_picture_url || c.user?.avatar;

        return {
          id: c.id?.toString(),
          userId: c.user?.id?.toString(),
          username,
          avatar: avatarUrl ? getMediaUrl(avatarUrl) : `https://ui-avatars.com/api/?name=${encodeURIComponent(username)}&background=667eea&color=fff&size=200&rounded=false&bold=true&format=svg`,
          text: c.content,
          createdAt: c.created_at
        };
      }
      return null;
    } catch (error) {
      console.error('Error adding omzo comment:', error);
      return null;
    }
  },

  // Comments (Scribe)
  getComments: async (scribeId: string): Promise<any[]> => {
    try {
      const response = await apiClient.get<any>(`/api/scribe/${scribeId}/comments/`);
      const comments = response.comments || [];
      return comments.map((c: any) => ({
        id: c.id?.toString(),
        userId: c.user?.id?.toString() || c.user_id?.toString(),
        username: c.user?.username || c.user_username,
        displayName: c.user?.display_name || c.user_full_name,
        avatar: getMediaUrl(c.user?.avatar || c.user_profile_picture || ''),
        text: c.content,
        createdAt: c.created_at || c.timestamp
      }));
    } catch (error) {
      console.error('Error fetching comments:', error);
      return [];
    }
  },

  addComment: async (scribeId: string, content: string): Promise<any | null> => {
    try {
      const response = await apiClient.post<any>('/api/add-comment/', { scribe_id: scribeId, content });
      if (response.success) {
        const c = response.comment;
        const username = c.user?.username || c.user_username || 'User';
        const avatarUrl = c.user?.profile_picture_url || c.user_profile_picture;

        return {
          id: c.id?.toString(),
          userId: c.user?.id?.toString() || c.user_id?.toString(),
          username,
          displayName: c.user?.display_name || c.user_full_name,
          avatar: avatarUrl ? getMediaUrl(avatarUrl) : `https://ui-avatars.com/api/?name=${encodeURIComponent(username)}&background=667eea&color=fff&size=200&rounded=false&bold=true&format=svg`,
          text: c.content,
          createdAt: c.created_at || c.timestamp
        };
      }
      return null;
    } catch (error) {
      console.error('Error adding comment:', error);
      return null;
    }
  },

  // Get User Profile
  getUserProfile: async (username: string): Promise<User | null> => {
    try {
      const response = await apiClient.get<any>(`/api/profile/${username}/`);
      const u = response.user;
      if (!u) return null;

      return {
        id: u.id?.toString() || '',
        username: u.username || '',
        displayName: u.display_name || u.full_name || u.username || '',
        avatar: getMediaUrl(u.avatar || u.profile_picture || ''),
        isOnline: u.is_online || false,
        isVerified: u.is_verified || false,
        followersCount: u.followers_count || 0,
        followingCount: u.following_count || 0,
        isFollowing: u.is_following || false,
      };
    } catch (error) {
      console.error('Error fetching user profile:', error);
      return null;
    }
  },

  // Get User Full Profile (including posts)
  getUserFullProfile: async (username: string): Promise<{ user: User; scribes: Scribe[]; reposts: Scribe[]; omzos: Omzo[] } | null> => {
    try {
      const response = await apiClient.get<any>(`/api/profile/${username}/`);
      const u = response.user;
      if (!u) return null;

      const user: User = {
        id: u.id?.toString() || '',
        username: u.username || '',
        displayName: u.display_name || u.full_name || u.username || '',
        avatar: getMediaUrl(u.avatar || u.profile_picture || ''),
        isOnline: u.is_online || false,
        isVerified: u.is_verified || false,
        followersCount: u.followers_count || u.follower_count || 0,
        followingCount: u.following_count || 0,
        isFollowing: u.is_following || false,
      };

      const scribes = (response.scribes || []).map((s: any) => {
        let type = (s.type || 'text');
        if (type === 'code_scribe') type = 'html';

        let htmlContent = undefined;
        if (type === 'html' && (s.code_html || s.code_css || s.code_js)) {
          htmlContent = `
                <!DOCTYPE html>
                <html>
                <head>
                  <style>
                    body { margin: 0; overflow: hidden; }
                    ${s.code_css || ''}
                  </style>
                </head>
                <body>
                  ${s.code_html || ''}
                  <script>
                    ${s.code_js || ''}
                  </script>
                </body>
                </html>
             `;
        }

        return {
          id: s.id?.toString(),
          user: user, // Attach the user object since it's their profile
          content: s.content || '',
          type: type as 'text' | 'image' | 'video' | 'html',
          htmlContent: htmlContent, // Add the constructed HTML content
          mediaUrl: getMediaUrl(s.media_url || ''),
          likes: s.likes || 0,
          dislikes: s.dislikes || 0,
          comments: s.comments || 0,
          reposts: s.reposts || 0,
          createdAt: new Date(s.timestamp || Date.now()),
          isLiked: s.is_liked || false,
          isDisliked: s.is_disliked || false,
          isSaved: s.is_saved || false,
        };
      });

      const reposts = (response.reposts || []).map((s: any) => {
        let type = (s.type || 'text');
        if (type === 'code_scribe') type = 'html';

        let htmlContent = undefined;
        if (type === 'html' && (s.code_html || s.code_css || s.code_js)) {
          htmlContent = `
                <!DOCTYPE html>
                <html>
                <head>
                  <style>
                    body { margin: 0; overflow: hidden; }
                    ${s.code_css || ''}
                  </style>
                </head>
                <body>
                  ${s.code_html || ''}
                  <script>
                    ${s.code_js || ''}
                  </script>
                </body>
                </html>
             `;
        }

        // Build original data if available
        let originalData = undefined;
        if (s.original_data) {
          const od = s.original_data;
          originalData = {
            id: od.id?.toString(),
            user: {
              id: od.user?.id?.toString() || '',
              username: od.user?.username || '',
              displayName: od.user?.display_name || od.user?.username || '',
              avatar: getMediaUrl(od.user?.avatar || ''),
              isOnline: od.user?.is_online || false,
              isVerified: od.user?.is_verified || false,
            },
            content: od.content || od.caption || '',
            caption: od.caption,
            type: od.type,
            mediaUrl: getMediaUrl(od.media_url || ''),
            videoUrl: getMediaUrl(od.video_url || ''),
            likes: od.likes || 0,
            comments: od.comments || 0,
            reposts: od.reposts || 0,
            views: od.views || 0,
            timestamp: new Date(od.timestamp || Date.now()),
          };
        }

        return {
          id: s.id?.toString(),
          user: user, // The person who reposted (profile owner)
          content: s.content || '',
          type: type as 'text' | 'image' | 'video' | 'html',
          htmlContent: htmlContent,
          mediaUrl: getMediaUrl(s.media_url || ''),
          likes: s.likes || 0,
          dislikes: s.dislikes || 0,
          comments: s.comments || 0,
          reposts: s.reposts || 0,
          createdAt: new Date(s.timestamp || Date.now()),
          isLiked: s.is_liked || false,
          isDisliked: s.is_disliked || false,
          isSaved: s.is_saved || false,
          isRepost: s.is_repost || false,
          originalType: s.original_type,
          originalData: originalData,
        };
      });

      // Handle different response structures for omzos
      let omzosData: any[] = [];
      if (response && typeof response === 'object') {
        if (Array.isArray(response.omzos)) {
          omzosData = response.omzos;
        } else if (Array.isArray(response.results)) {
          omzosData = response.results;
        } else if (Array.isArray(response.data)) {
          omzosData = response.data;
        } else if (Array.isArray(response)) {
          omzosData = response;
        } else {
          console.warn('Unexpected omzos response structure in getUserFullProfile:', response);
          omzosData = [];
        }
      } else {
        console.warn('Invalid omzos response in getUserFullProfile:', response);
        omzosData = [];
      }

      const omzos = omzosData.map((o: any) => ({
        id: o.id?.toString(),
        user: user,
        videoUrl: getMediaUrl(o.video_url || ''),
        caption: o.caption || '',
        audioName: 'Original Sound', // Default since not in simplified response
        likes: o.likes || 0,
        dislikes: o.dislikes || 0,
        views: o.views || 0,
        comments: o.comments || 0,
        shares: o.shares || 0,
        reposts: o.reposts || 0,
        createdAt: new Date(o.timestamp || Date.now()),
        isLiked: o.is_liked || false,
        isSaved: o.is_saved || false,
      }));

      return { user, scribes, reposts, omzos };
    } catch (error) {
      console.error('Error fetching full user profile:', error);
      return null;
    }
  },

  // Update Profile
  updateProfile: async (formData: FormData): Promise<User | null> => {
    try {
      const response = await apiClient.post<any>('/api/profile/', formData);
      const u = response.user;
      if (!u) return null;

      return {
        id: u.id?.toString() || '',
        username: u.username || '',
        displayName: u.display_name || u.full_name || u.username || '',
        avatar: getMediaUrl(u.avatar || u.profile_picture || ''),
        isOnline: u.is_online || false,
        isVerified: u.is_verified || false,
      };
    } catch (error) {
      console.error('Error updating profile:', error);
      return null;
    }
  },

  // Upload Omzo
  uploadOmzo: async (formData: FormData, onProgress?: (progress: number) => void): Promise<boolean> => {
    try {
      const response = await apiClient.upload<any>('/api/omzo/upload/', formData, onProgress);
      return !!response?.success; // Adjust dependent on actual backend response structure
    } catch (error) {
      console.error('Error uploading omzo:', error);
      return false;
    }
  },

  // Create Story
  createStory: async (formData: FormData): Promise<boolean> => {
    try {
      const response = await apiClient.post<any>('/api/create-story/', formData);
      return !!response?.success;
    } catch (error) {
      console.error('Error creating story:', error);
      return false;
    }
  },

  // Post Scribe
  postScribe: async (formData: FormData): Promise<{ success: boolean; error?: string }> => {
    try {
      const response = await apiClient.post<any>('/api/post-scribe/', formData);
      return { success: !!response?.success, error: response?.error };
    } catch (error) {
      console.error('Error posting scribe:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
    }
  },

  // WebRTC P2P
  getP2PSignals: async (chatId: string): Promise<any[]> => {
    try {
      const response = await apiClient.get<any>(`/api/p2p/${chatId}/signals/`);
      return response.signals || response || [];
    } catch (err) {
      console.error("Error fetching signals", err);
      return [];
    }
  },

  sendP2PSignal: async (chatId: string, signalData: any, targetUserId?: string): Promise<boolean> => {
    try {
      await apiClient.post('/api/p2p/send-signal/', {
        chat_id: chatId,
        signal_data: signalData,
        target_user_id: targetUserId
      });
      return true;
    } catch (err) {
      console.error("Error sending p2p signal", err);
      return false;
    }
  },

  markMessagesRead: async (chatId: string): Promise<boolean> => {
    try {
      await apiClient.post(`/api/chat/${chatId}/mark-read/`);
      return true;
    } catch (error) {
      console.error('Error marking messages as read:', error);
      return false;
    }
  },

  // Report Functions
  reportPost: async (
    scribeId: string,
    reason: string,
    description?: string,
    copyrightDescription?: string,
    copyrightType?: 'audio' | 'content' | 'both'
  ): Promise<{ success: boolean; message?: string; error?: string }> => {
    try {
      const response = await apiClient.post<any>('/api/report-post/', {
        scribe_id: scribeId,
        reason,
        description: description || '',
        copyright_description: copyrightDescription || '',
        copyright_type: copyrightType || ''
      });
      return {
        success: response.success,
        message: response.message,
        error: response.error
      };
    } catch (error: any) {
      console.error('Error reporting post:', error);
      return {
        success: false,
        error: error.response?.data?.error || 'Failed to report post'
      };
    }
  },

  reportOmzo: async (
    omzoId: string,
    reason: string,
    description?: string,
    copyrightDescription?: string,
    copyrightType?: 'audio' | 'content' | 'both',
    disableAudio?: boolean
  ): Promise<{ success: boolean; message?: string; error?: string }> => {
    try {
      const response = await apiClient.post<any>('/api/omzo/report/', {
        omzo_id: omzoId,
        reason,
        description: description || '',
        copyright_description: copyrightDescription || '',
        copyright_type: copyrightType || '',
        disable_audio: disableAudio || false
      });
      return {
        success: response.success,
        message: response.message,
        error: response.error
      };
    } catch (error: any) {
      console.error('Error reporting omzo:', error);
      return {
        success: false,
        error: error.response?.data?.error || 'Failed to report omzo'
      };
    }
  },

  // Get single Scribe by ID
  getScribe: async (scribeId: string): Promise<any | null> => {
    try {
      const response = await apiClient.get<any>(`/api/scribe/${scribeId}/`);
      const s = response.scribe;
      if (!s) return null;

      // Map backend scribe to frontend Scribe interface safely
      return {
        id: s.id?.toString(),
        user: {
          id: s.id?.toString(), // simplistic fallback as user_id might be missing in detail view sometimes
          username: s.username,
          displayName: s.full_name || s.username,
          avatar: getMediaUrl(s.avatar || ''),
          isOnline: false,
          isVerified: false
        },
        content: s.content || '',
        type: s.image_url ? 'image' : 'text',
        mediaUrl: getMediaUrl(s.image_url || ''),
        likes: s.like_count || 0,
        dislikes: 0,
        comments: s.comment_count || 0,
        reposts: 0,
        createdAt: new Date(s.timestamp),
        isLiked: s.is_liked || false,
        isDisliked: s.is_disliked || false,
        isSaved: s.is_saved || false,
      };
    } catch (error) {
      console.error('Error fetching scribe:', error);
      return null;
    }
  },

  // Get single Omzo by ID
  getOmzo: async (omzoId: string): Promise<Omzo | null> => {
    try {
      const response = await apiClient.get<any>(`/api/omzo/${omzoId}/details/`);

      if (!response.success && response.error) {
        throw new Error(response.error);
      }

      const o = response.omzo;
      if (!o) throw new Error('Omzo data missing');

      return {
        id: o.id?.toString(),
        user: {
          id: o.user.id?.toString(),
          username: o.user.username,
          displayName: o.user.displayName,
          avatar: getMediaUrl(o.user.avatar || ''),
          isOnline: o.user.isOnline || false,
          isVerified: o.user.isVerified || false,
        },
        videoUrl: getMediaUrl(o.videoUrl || ''),
        caption: o.caption || '',
        audioName: o.audioName || 'Original Sound',
        likes: o.likes || 0,
        dislikes: o.dislikes || 0,
        views: o.views || 0,
        comments: o.comments || 0,
        shares: o.shares || 0,
        reposts: o.reposts || 0,
        createdAt: new Date(o.createdAt),
        isLiked: o.isLiked || false,
        isDisliked: o.isDisliked || false,
        isSaved: o.isSaved || false,
      };
    } catch (error: any) {
      console.error('Error fetching omzo:', error);
      throw new Error(error.response?.data?.error || error.message || 'Failed to fetch omzo');
    }
  },

  // Logout
  logout: async (): Promise<boolean> => {
    try {
      const response = await apiClient.post<any>('/api/logout/', {});
      return !!response?.success;
    } catch (error) {
      console.error('Error logging out:', error);
      return false;
    }
  },

  // Message Context Menu
  getMessageContextMenu: async (messageId: string, chatId: string, isOwn: boolean): Promise<any> => {
    try {
      const response = await apiClient.get<any>(`/api/message/${messageId}/context-menu/`);
      return response;
    } catch (error) {
      console.error('Error fetching context menu:', error);
      throw error;
    }
  },

  executeMessageAction: async (messageId: string, action: string, data?: any): Promise<any> => {
    try {
      const response = await apiClient.post<any>('/api/message/context-action/', {
        message_id: messageId,
        action,
        ...data
      });
      return response;
    } catch (error) {
      console.error('Error executing message action:', error);
      throw error;
    }
  },

  // Group Chat
  createGroup: async (name: string, participantIds: string[], description?: string, isPublic: boolean = false, avatar?: File | null): Promise<Chat | null> => {
    try {
      const formData = new FormData();
      formData.append('name', name);
      formData.append('participants', JSON.stringify(participantIds));
      if (description) formData.append('description', description);
      formData.append('is_public', String(isPublic));

      if (avatar) {
        formData.append('avatar', avatar);
      }

      const response = await apiClient.post<any>('/api/create-group/', formData);

      if (response.success && response.group) {
        // Map response to Chat interface
        // Note: The backend response structure for 'group' needs to be mapped correctly.
        // Assuming backend returns basic group info; we might need to fetch full details or mock initial state.
        const g = response.group;
        return {
          id: g.id?.toString(),
          user: { id: 'group', username: 'Group', displayName: name, avatar: g.groupAvatar || '', isOnline: false }, // Placeholder user
          lastMessage: 'Group created',
          timestamp: new Date(),
          unreadCount: 0,
          isPrivate: false,
          chat_type: 'group',
          name: g.name,
          participants: [], // Details might need separate fetch or be included
          groupAvatar: g.groupAvatar
        };
      }
      return null;
    } catch (error) {
      console.error('Error creating group:', error);
      return null;
    }
  },

  searchUsersPublic: async (query?: string): Promise<User[]> => {
    try {
      const q = query || '';
      const response = await apiClient.get<any>(`/api/share/search-users/?q=${encodeURIComponent(q)}`);
      const users = response.results || response.users || [];

      return users.map((u: any) => ({
        id: u.id?.toString(),
        username: u.username,
        displayName: u.full_name || u.username,
        avatar: getMediaUrl(u.avatar_url || u.profile_picture || ''),
        isOnline: u.is_online !== undefined ? u.is_online : false,
        isVerified: u.is_verified || false
      }));
    } catch (error) {
      console.error('Error searching users:', error);
      return [];
    }
  },
};

