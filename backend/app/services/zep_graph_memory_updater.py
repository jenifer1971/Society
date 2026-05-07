"""
Graph memory updater — stores agent simulation activities in PostgreSQL.

Public API (ZepGraphMemoryUpdater, ZepGraphMemoryManager, AgentActivity) is
unchanged so all callers work without modification.
"""

import threading
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty

from ..config import Config
from ..db import get_conn
from ..utils.logger import get_logger
from ..utils.locale import get_locale, set_locale

logger = get_logger('mirofish.zep_graph_memory_updater')


@dataclass
class AgentActivity:
    """Agent activity record."""
    platform: str
    agent_id: int
    agent_name: str
    action_type: str
    action_args: Dict[str, Any]
    round_num: int
    timestamp: str

    def to_episode_text(self) -> str:
        action_descriptions = {
            "CREATE_POST": self._describe_create_post,
            "LIKE_POST": self._describe_like_post,
            "DISLIKE_POST": self._describe_dislike_post,
            "REPOST": self._describe_repost,
            "QUOTE_POST": self._describe_quote_post,
            "FOLLOW": self._describe_follow,
            "CREATE_COMMENT": self._describe_create_comment,
            "LIKE_COMMENT": self._describe_like_comment,
            "DISLIKE_COMMENT": self._describe_dislike_comment,
            "SEARCH_POSTS": self._describe_search,
            "SEARCH_USER": self._describe_search_user,
            "MUTE": self._describe_mute,
        }
        describe_func = action_descriptions.get(self.action_type, self._describe_generic)
        return f"{self.agent_name}: {describe_func()}"

    def _describe_create_post(self) -> str:
        content = self.action_args.get("content", "")
        return f"发布了一条帖子：「{content}」" if content else "发布了一条帖子"

    def _describe_like_post(self) -> str:
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        if post_content and post_author:
            return f"点赞了{post_author}的帖子：「{post_content}」"
        elif post_content:
            return f"点赞了一条帖子：「{post_content}」"
        elif post_author:
            return f"点赞了{post_author}的一条帖子"
        return "点赞了一条帖子"

    def _describe_dislike_post(self) -> str:
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        if post_content and post_author:
            return f"踩了{post_author}的帖子：「{post_content}」"
        elif post_content:
            return f"踩了一条帖子：「{post_content}」"
        elif post_author:
            return f"踩了{post_author}的一条帖子"
        return "踩了一条帖子"

    def _describe_repost(self) -> str:
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        if original_content and original_author:
            return f"转发了{original_author}的帖子：「{original_content}」"
        elif original_content:
            return f"转发了一条帖子：「{original_content}」"
        elif original_author:
            return f"转发了{original_author}的一条帖子"
        return "转发了一条帖子"

    def _describe_quote_post(self) -> str:
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        quote_content = self.action_args.get("quote_content", "") or self.action_args.get("content", "")
        base = ""
        if original_content and original_author:
            base = f"引用了{original_author}的帖子「{original_content}」"
        elif original_content:
            base = f"引用了一条帖子「{original_content}」"
        elif original_author:
            base = f"引用了{original_author}的一条帖子"
        else:
            base = "引用了一条帖子"
        if quote_content:
            base += f"，并评论道：「{quote_content}」"
        return base

    def _describe_follow(self) -> str:
        target_user_name = self.action_args.get("target_user_name", "")
        return f"关注了用户「{target_user_name}」" if target_user_name else "关注了一个用户"

    def _describe_create_comment(self) -> str:
        content = self.action_args.get("content", "")
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")
        if content:
            if post_content and post_author:
                return f"在{post_author}的帖子「{post_content}」下评论道：「{content}」"
            elif post_content:
                return f"在帖子「{post_content}」下评论道：「{content}」"
            elif post_author:
                return f"在{post_author}的帖子下评论道：「{content}」"
            return f"评论道：「{content}」"
        return "发表了评论"

    def _describe_like_comment(self) -> str:
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        if comment_content and comment_author:
            return f"点赞了{comment_author}的评论：「{comment_content}」"
        elif comment_content:
            return f"点赞了一条评论：「{comment_content}」"
        elif comment_author:
            return f"点赞了{comment_author}的一条评论"
        return "点赞了一条评论"

    def _describe_dislike_comment(self) -> str:
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")
        if comment_content and comment_author:
            return f"踩了{comment_author}的评论：「{comment_content}」"
        elif comment_content:
            return f"踩了一条评论：「{comment_content}」"
        elif comment_author:
            return f"踩了{comment_author}的一条评论"
        return "踩了一条评论"

    def _describe_search(self) -> str:
        query = self.action_args.get("query", "") or self.action_args.get("keyword", "")
        return f"搜索了「{query}」" if query else "进行了搜索"

    def _describe_search_user(self) -> str:
        query = self.action_args.get("query", "") or self.action_args.get("username", "")
        return f"搜索了用户「{query}」" if query else "搜索了用户"

    def _describe_mute(self) -> str:
        target_user_name = self.action_args.get("target_user_name", "")
        return f"屏蔽了用户「{target_user_name}」" if target_user_name else "屏蔽了一个用户"

    def _describe_generic(self) -> str:
        return f"执行了{self.action_type}操作"


class ZepGraphMemoryUpdater:
    """
    Buffers agent activities from the simulation and writes them to
    the graph_episodes table in PostgreSQL in small batches.
    """

    BATCH_SIZE = 5
    PLATFORM_DISPLAY_NAMES = {'twitter': '世界1', 'reddit': '世界2'}

    def __init__(self, graph_id: str, api_key: Optional[str] = None):
        self.graph_id = graph_id

        self._activity_queue: Queue = Queue()
        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            'twitter': [], 'reddit': [],
        }
        self._buffer_lock = threading.Lock()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        self._total_activities = 0
        self._total_sent = 0
        self._total_items_sent = 0
        self._failed_count = 0
        self._skipped_count = 0

        # Temporal tracking — activated via ENABLE_TEMPORAL_TRACKING=true
        self._temporal_tracker = None
        if Config.ENABLE_TEMPORAL_TRACKING:
            try:
                from .temporal_tracker import TemporalTracker
                self._temporal_tracker = TemporalTracker()
                logger.info(f"Temporal tracking enabled for graph {graph_id}")
            except Exception as e:
                logger.warning(f"Temporal tracker init failed: {e}")

    def start(self):
        if self._running:
            return
        current_locale = get_locale()
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(current_locale,),
            daemon=True,
            name=f"MemoryUpdater-{self.graph_id[:8]}",
        )
        self._worker_thread.start()

    def stop(self):
        self._running = False
        self._flush_remaining()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)

    def add_activity(self, activity: AgentActivity):
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return
        self._activity_queue.put(activity)
        self._total_activities += 1

    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        if "event_type" in data:
            return
        activity = AgentActivity(
            platform=platform,
            agent_id=data.get("agent_id", 0),
            agent_name=data.get("agent_name", ""),
            action_type=data.get("action_type", ""),
            action_args=data.get("action_args", {}),
            round_num=data.get("round", 0),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )
        self.add_activity(activity)

    def _worker_loop(self, locale: str = 'zh'):
        set_locale(locale)
        while self._running or not self._activity_queue.empty():
            try:
                try:
                    activity = self._activity_queue.get(timeout=1)
                    platform = activity.platform.lower()
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)
                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][:self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE:]
                            self._send_batch(batch, platform)
                except Empty:
                    pass
            except Exception as e:
                logger.error(f"Worker loop error: {e}")

    def _send_batch(self, activities: List[AgentActivity], platform: str):
        if not activities:
            return
        combined = "\n".join(a.to_episode_text() for a in activities)
        round_num = activities[-1].round_num if activities else 0

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO graph_episodes (graph_id, content, platform, round_num)
                           VALUES (%s, %s, %s, %s)""",
                        (self.graph_id, combined, platform, round_num),
                    )
            self._total_sent += 1
            self._total_items_sent += len(activities)
            display = self.PLATFORM_DISPLAY_NAMES.get(platform, platform)
            logger.info(f"Stored {len(activities)} {display} activities for graph {self.graph_id}")
        except Exception as e:
            logger.error(f"Failed to store batch: {e}")
            self._failed_count += 1
            return

        # Temporal tracking — runs in background, never blocks simulation
        if self._temporal_tracker is not None:
            import threading
            threading.Thread(
                target=self._temporal_tracker.process_activity_batch,
                args=(self.graph_id, combined, round_num),
                daemon=True,
                name=f"TemporalTracker-{self.graph_id[:8]}-r{round_num}",
            ).start()

    def _flush_remaining(self):
        while not self._activity_queue.empty():
            try:
                activity = self._activity_queue.get_nowait()
                platform = activity.platform.lower()
                with self._buffer_lock:
                    self._platform_buffers.setdefault(platform, []).append(activity)
            except Empty:
                break

        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    self._send_batch(buffer, platform)
            for p in self._platform_buffers:
                self._platform_buffers[p] = []

    def get_stats(self) -> Dict[str, Any]:
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}
        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,
            "batches_sent": self._total_sent,
            "items_sent": self._total_items_sent,
            "failed_count": self._failed_count,
            "skipped_count": self._skipped_count,
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,
            "running": self._running,
        }


class ZepGraphMemoryManager:
    """Manages per-simulation memory updater instances."""

    _updaters: Dict[str, ZepGraphMemoryUpdater] = {}
    _lock = threading.Lock()
    _stop_all_done = False

    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> ZepGraphMemoryUpdater:
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
            updater = ZepGraphMemoryUpdater(graph_id)
            updater.start()
            cls._updaters[simulation_id] = updater
        return updater

    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[ZepGraphMemoryUpdater]:
        return cls._updaters.get(simulation_id)

    @classmethod
    def stop_updater(cls, simulation_id: str):
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]

    @classmethod
    def stop_all(cls):
        if cls._stop_all_done:
            return
        cls._stop_all_done = True
        with cls._lock:
            for sim_id, updater in list(cls._updaters.items()):
                try:
                    updater.stop()
                except Exception as e:
                    logger.error(f"Failed to stop updater {sim_id}: {e}")
            cls._updaters.clear()

    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        return {sid: u.get_stats() for sid, u in cls._updaters.items()}
