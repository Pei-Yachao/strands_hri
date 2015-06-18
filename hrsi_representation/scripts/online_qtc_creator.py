#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 27 16:03:38 2015

@author: cdondrup
"""

import rospy
from geometry_msgs.msg import PoseStamped, Pose
from bayes_people_tracker.msg import PeopleTracker
from dynamic_reconfigure.server import Server as DynServer
from hrsi_representation.cfg import OnlineQTCCreatorConfig
from hrsi_representation.msg import QTCArray, QTC
from hrsi_representation.online_input import OnlineInput
import numpy as np
import tf
import json
import thread

class OnlineQTCCreator(object):
    """Creates QTC state sequences from online input"""

    _qtc_types = {
        0: "qtcb",
        1: "qtcc",
        2: "qtcbc"
    }
    _robot_pose = None
    _buffer = dict()
    _smoothing_buffer = dict()
    _msg_buffer = []

    def __init__(self, name):
        rospy.loginfo("Starting %s" % name)
        self.input           = OnlineInput()
        ppl_topic            = rospy.get_param("~ppl_topic", "/people_tracker/positions")
        robot_topic          = rospy.get_param("~robot_topic", "/robot_pose")
        self.target_frame    = rospy.get_param("~target_frame", "/map")
        self.decay_time      = rospy.get_param("~decay_time", 120.)
        self.processing_rate = rospy.get_param("~processing_rate", 30)
        self.dyn_srv         = DynServer(OnlineQTCCreatorConfig, self.dyn_callback)
        self.listener        = tf.TransformListener()
        self.pub             = rospy.Publisher("~qtc_array", QTCArray, queue_size=10)
        self.last_msg        = QTCArray()
        rospy.Subscriber(
            ppl_topic,
            PeopleTracker,
            callback=self.ppl_callback,
            queue_size=10
        )
        rospy.Subscriber(
            robot_topic,
            Pose,
            callback=self.pose_callback,
            queue_size=10
        )

        self.request_thread = thread.start_new(self.generate_qtc, ())

    def dyn_callback(self, config, level):
        self.qtc_type            = self._qtc_types[config["qtc_type"]]
        self.quantisation_factor = config["quantisation_factor"]
        self.distance_threshold  = config["distance_threshold"]
        self.validate            = config["validate"]
        self.no_collapse         = config["no_collapse"]
        self.smoothing_rate      = config["smoothing_rate"]
        return config

    def ppl_callback(self, msg):
        msgs = {
            "ppl": msg,
            "robot": self._robot_pose
        }
        self._msg_buffer.append(msgs)

    def pose_callback(self, msg):
        self._robot_pose = msg

    def generate_qtc(self):
        rate = rospy.Rate(self.processing_rate)
        while not rospy.is_shutdown():
            if not self._msg_buffer:
                rate.sleep()
                continue

            ppl_msg = self._msg_buffer[0]["ppl"]
            robot_msg = self._msg_buffer[0]["robot"]
            del self._msg_buffer[0]
            # Creating an new message
            out = QTCArray()
            out.header = ppl_msg.header
            out.header.frame_id = self.target_frame

            # Looping through detected humans
            for (uuid, pose) in zip(ppl_msg.uuids, ppl_msg.poses):
                # Transforming pose into target_frame if necessary
                person = PoseStamped()
                person.header = ppl_msg.header
                person.pose = pose
                if ppl_msg.header.frame_id != self.target_frame:
                    try:
                        self.listener.waitForTransform(ppl_msg.header.frame_id, self.target_frame, ppl_msg.header.stamp, rospy.Duration(1.0))
                        transformed = self.listener.transformPose(self.target_frame, person)
                    except (tf.Exception, tf.LookupException, tf.ConnectivityException) as ex:
                        rospy.logwarn(ex)
                        return
                else:
                    transformed = person


                if not uuid in self._smoothing_buffer.keys(): # No entry yet
                    self._smoothing_buffer[uuid] = {
                        "start_time": ppl_msg.header.stamp.to_sec(),
                        "data": np.array(
                            [
                                robot_msg.position.x,
                                robot_msg.position.y,
                                transformed.pose.position.x,
                                transformed.pose.position.y
                            ]
                    ).reshape(-1,4), "last_seen": ppl_msg.header.stamp.to_sec()}
                else: # Already in buffer
                    self._smoothing_buffer[uuid]["data"] = np.append(
                        self._smoothing_buffer[uuid]["data"],
                        [
                            robot_msg.position.x,
                            robot_msg.position.y,
                            transformed.pose.position.x,
                            transformed.pose.position.y
                        ]
                    ).reshape(-1,4)

            # Flush smoothing buffer and create QSR
            # Looping through smoothing buffer
            for uuid, data in self._smoothing_buffer.items():
                # If the smoothing time is not up, do nothing for this entry
                if not data["start_time"] + self.smoothing_rate <= ppl_msg.header.stamp.to_sec():
                    continue

                # Put smoothed values in buffer
                if not uuid in self._buffer.keys(): # No entry yet, create a new one
                    self._buffer[uuid] = {"data": np.array(
                        [
                            np.mean(data["data"][:,0]), # Mean over the coordinates to smooth them
                            np.mean(data["data"][:,1]),
                            np.mean(data["data"][:,2]),
                            np.mean(data["data"][:,3])
                        ]
                    ).reshape(-1,4), "last_seen": ppl_msg.header.stamp.to_sec()}
                else: # Already in buffer, append latest values
                    self._buffer[uuid]["data"] = np.append(
                        self._buffer[uuid]["data"],
                        [
                            np.mean(data["data"][:,0]),
                            np.mean(data["data"][:,1]),
                            np.mean(data["data"][:,2]),
                            np.mean(data["data"][:,3])
                        ]
                    ).reshape(-1,4)
                self._buffer[uuid]["last_seen"] = ppl_msg.header.stamp.to_sec() # Add time of laast update for decay

                del self._smoothing_buffer[uuid] # Delete element from smoothing buffer

                # If there are more than 1 entries in the buffer for this person
                # Create QTC representation
                if self._buffer[uuid]["data"].shape[0] > 1:
                    qtc = self.input.convert(
                        data=self.input.generate_data_from_input(
                            agent1="Robot",
                            agent2="Human",
                            x1=self._buffer[uuid]["data"][:,0],
                            y1=self._buffer[uuid]["data"][:,1],
                            x2=self._buffer[uuid]["data"][:,2],
                            y2=self._buffer[uuid]["data"][:,3]
                        ),
                        qtc_type=self.qtc_type,
                        quantisation_factor=self.quantisation_factor,
                        validate=self.validate,
                        no_collapse=self.no_collapse,
                        distance_threshold=self.distance_threshold
                    )[0]

                    # Create new message
                    qtc_msg                     = QTC()
                    qtc_msg.collapsed           = not self.no_collapse
                    qtc_msg.qtc_type            = self.qtc_type
                    qtc_msg.k                   = "Robot"
                    qtc_msg.l                   = "Human"
                    qtc_msg.quantisation_factor = self.quantisation_factor
                    qtc_msg.distance_threshold  = self.distance_threshold
                    qtc_msg.smoothing_rate      = self.smoothing_rate
                    qtc_msg.validated           = self.validate
                    qtc_msg.uuid                = uuid
                    qtc_msg.qtc_serialised      = json.dumps(qtc.tolist())

                    out.qtc.append(qtc_msg)

            # If there is something to publish and it heasn't been published before, publish
            if out.qtc and out.qtc != self.last_msg.qtc:
                self.pub.publish(out)
                self.last_msg = out
            self.decay(ppl_msg.header.stamp) # Delete old elements from buffer
            rate.sleep()

    def decay(self, last_time):
        for uuid in self._buffer.keys():
            if self._buffer[uuid]["last_seen"] + self.decay_time < last_time.to_sec():
                del self._buffer[uuid]

if __name__ == "__main__":
    rospy.init_node("online_qtc_creator")
    oqc = OnlineQTCCreator(rospy.get_name())
    rospy.spin()
