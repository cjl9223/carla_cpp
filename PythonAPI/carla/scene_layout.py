# Copyright (c) 2019 Computer Vision Center (CVC) at the Universitat Autonoma de
# Barcelona (UAB).
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.
# Provides map data for users.

import glob  # 用于文件路径的模式匹配
import os  # 提供了许多与操作系统交互的功能
import sys  # 提供了一些变量和函数，用来操纵Python运行时环境
 
try:
    # 尝试将符合特定模式的CARLA egg文件路径添加到系统路径中，以便导入CARLA模块
    # 该模式基于Python版本（major.minor）和操作系统（Windows或Linux）
    sys.path.append(glob.glob('dist/carla-*%d.%d-%s.egg' % (
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError:
    # 如果没有找到符合条件的egg文件，则忽略此异常
    pass
 
import carla  # 导入CARLA模块
import random  # 导入random模块，尽管在这段代码中未直接使用
 
def get_scene_layout(carla_map):
    """
    提取完整的场景布局，作为完整的场景描述返回给用户。
    
    :param carla_map: CARLA地图对象
    :return: 描述场景的字典
    """
    
    def _lateral_shift(transform, shift):
        # 将变换的旋转yaw增加90度，然后沿着变换的前向向量移动指定的偏移量
        transform.rotation.yaw += 90
        return transform.location + shift * transform.get_forward_vector()
    
    # 获取并排序地图的拓扑结构，按道路的高度排序
    topology = [x[0] for x in carla_map.get_topology()]
    topology = sorted(topology, key=lambda w: w.transform.location.z)
    
    # 初始化一个字典来存储地图信息
    map_dict = dict()
    precision = 0.05  # 设置精度
    
    # 遍历拓扑结构中的每个waypoint（路径点）
    for waypoint in topology:
        waypoints = [waypoint]
        nxt = waypoint.next(precision)  # 获取下一个路径点
        while nxt and nxt[0].road_id == waypoint.road_id:  # 如果下一个路径点在同一道路上
            waypoints.append(nxt[0])  # 添加到当前路径点的列表中
            nxt = nxt[0].next(precision)  # 继续获取下一个路径点
        
        # 计算左右车道线的位置
        left_marking = [_lateral_shift(w.transform, -w.lane_width * 0.5) for w in waypoints]
        right_marking = [_lateral_shift(w.transform, w.lane_width * 0.5) for w in waypoints]
        
        # 将路径点及其左右车道线信息添加到map_dict中
        lane = {"waypoints": waypoints, "left_marking": left_marking, "right_marking": right_marking}
        if map_dict.get(waypoint.road_id) is None:
            map_dict[waypoint.road_id] = {}
        map_dict[waypoint.road_id][waypoint.lane_id] = lane
    
    # 生成路径点图
    waypoints_graph = dict()
    for road_key in map_dict:
        for lane_key in map_dict[road_key]:
            lane = map_dict[road_key][lane_key]
            for i in range(len(lane["waypoints"])):
                # 获取当前路径点的后续路径点ID
                next_ids = [w.id for w in lane["waypoints"][i + 1:]]
                
                # 计算左右车道键
                left_lane_key = lane_key - 1 if lane_key - 1 else lane_key - 2
                right_lane_key = lane_key + 1 if lane_key + 1 else lane_key + 2
                
                # 获取左右车道路径点的ID（如果存在）
                left_lane_waypoint_id = -1
                if left_lane_key in map_dict[road_key]:
                    left_lane_waypoints = map_dict[road_key][left_lane_key]["waypoints"]
                    if i < len(left_lane_waypoints):
                        left_lane_waypoint_id = left_lane_waypoints[i].id
                
                right_lane_waypoint_id = -1
                if right_lane_key in map_dict[road_key]:
                    right_lane_waypoints = map_dict[road_key][right_lane_key]["waypoints"]
                    if i < len(right_lane_waypoints):
                        right_lane_waypoint_id = right_lane_waypoints[i].id
                
                # 获取左右边界（车道线）和当前路径点的地理位置和朝向
                lm = carla_map.transform_to_geolocation(lane["left_marking"][i])
                rm = carla_map.transform_to_geolocation(lane["right_marking"][i])
                wl = carla_map.transform_to_geolocation(lane["waypoints"][i].transform.location)
                wo = lane["waypoints"][i].transform.rotation
                
                # 创建当前路径点的字典
                waypoint_dict = {
                    "road_id": road_key,
                    "lane_id": lane_key,
                    "position": [wl.latitude, wl.longitude, wl.altitude],
                    "orientation": [wo.roll, wo.pitch, wo.yaw],
                    "left_margin_position": [lm.latitude, lm.longitude, lm.altitude],
                    "right_margin_position": [rm.latitude, rm.longitude, rm.altitude],
                    "next_waypoints_ids": next_ids,
                    "left_lane_waypoint_id": left_lane_waypoint_id,
                    "right_lane_waypoint_id": right_lane_waypoint_id
                }
                waypoints_graph[map_dict[road_key][lane_key]["waypoints"][i].id] = waypoint_dict
    
    return waypoints_graph  # 返回路径点图
 
def get_dynamic_objects(carla_world, carla_map):
    """
    获取CARLA世界中的动态对象信息。
    
    :param carla_world: CARLA世界对象
    :param carla_map: CARLA地图对象
    :return: 包含不同类型动态对象的元组
    """
    
    def _get_bounding_box(actor):
        # 获取演员的包围盒的角点坐标（经纬度海拔）
        bb = actor.bounding_box.extent
        corners = [carla.Location(x=-bb.x, y=-bb.y), carla.Location(x=bb.x, y=-bb.y),
                   carla.Location(x=bb.x, y=bb.y), carla.Location(x=-bb.x, y=bb.y)]
        t = actor.get_transform()
        t.transform(corners)
        corners = [carla_map.transform_to_geolocation(p) for p in corners]
        return corners
    
    def _get_trigger_volume(actor):
        # 获取演员的触发体积的角点坐标（经纬度海拔）
        bb = actor.trigger_volume.extent
        corners = [carla.Location(x=-bb.x, y=-bb.y), carla.Location(x=bb.x, y=-bb.y),
                   carla.Location(x=bb.x, y=bb.y), carla.Location(x=-bb.x, y=bb.y),
                   carla.Location(x=-bb.x, y=-bb.y)]  # 注意这里最后一个点是重复的，形成一个闭合的多边形
        corners = [x + actor.trigger_volume.location for x in corners]
        t = actor.get_transform()
        t.transform(corners)
        corners = [carla_map.transform_to_geolocation(p) for p in corners]
        return corners

    def _split_actors(actors):
        vehicles = []
        traffic_lights = []
        speed_limits = []
        walkers = []
        stops = []
        static_obstacles = []
        for actor in actors:
            if 'vehicle' in actor.type_id:
                vehicles.append(actor)
            elif 'traffic_light' in actor.type_id:
                traffic_lights.append(actor)
            elif 'speed_limit' in actor.type_id:
                speed_limits.append(actor)
            elif 'walker' in actor.type_id:
                walkers.append(actor)
            elif 'stop' in actor.type_id:
                stops.append(actor)
            elif 'static.prop' in actor.type_id:
                static_obstacles.append(actor)


        return (vehicles, traffic_lights, speed_limits, walkers, stops, static_obstacles)

    # Public functions
    def get_stop_signals(stops):
        stop_signals_dict = dict()
        for stop in stops:
            st_transform = stop.get_transform()
            location_gnss = carla_map.transform_to_geolocation(st_transform.location)
            st_dict = {
                "id": stop.id,
                "position": [location_gnss.latitude, location_gnss.longitude, location_gnss.altitude],
                "trigger_volume": [[v.longitude, v.latitude, v.altitude] for v in _get_trigger_volume(stop)]
            }
            stop_signals_dict[stop.id] = st_dict
        return stop_signals_dict

    def get_traffic_lights(traffic_lights):
        traffic_lights_dict = dict()
        for traffic_light in traffic_lights:
            tl_transform = traffic_light.get_transform()
            location_gnss = carla_map.transform_to_geolocation(tl_transform.location)
            tl_dict = {
                "id": traffic_light.id,
                "state": int(traffic_light.state),
                "position": [location_gnss.latitude, location_gnss.longitude, location_gnss.altitude],
                "trigger_volume": [[v.longitude, v.latitude, v.altitude] for v in _get_trigger_volume(traffic_light)]
            }
            traffic_lights_dict[traffic_light.id] = tl_dict
        return traffic_lights_dict

    def get_vehicles(vehicles):
        vehicles_dict = dict()
        for vehicle in vehicles:
            v_transform = vehicle.get_transform()
            location_gnss = carla_map.transform_to_geolocation(v_transform.location)
            v_dict = {
                "id": vehicle.id,
                "position": [location_gnss.latitude, location_gnss.longitude, location_gnss.altitude],
                "orientation": [v_transform.rotation.roll, v_transform.rotation.pitch, v_transform.rotation.yaw],
                "bounding_box": [[v.longitude, v.latitude, v.altitude] for v in _get_bounding_box(vehicle)]
            }
            vehicles_dict[vehicle.id] = v_dict
        return vehicles_dict

    def get_hero_vehicle(hero_vehicle):
        if hero_vehicle is None:
            return hero_vehicle

        hero_waypoint = carla_map.get_waypoint(hero_vehicle.get_location())
        hero_transform = hero_vehicle.get_transform()
        location_gnss = carla_map.transform_to_geolocation(hero_transform.location)

        hero_vehicle_dict = {
            "id": hero_vehicle.id,
            "position": [location_gnss.latitude, location_gnss.longitude, location_gnss.altitude],
            "road_id": hero_waypoint.road_id,
            "lane_id": hero_waypoint.lane_id
        }
        return hero_vehicle_dict

    def get_walkers(walkers):
        walkers_dict = dict()
        for walker in walkers:
            w_transform = walker.get_transform()
            location_gnss = carla_map.transform_to_geolocation(w_transform.location)
            w_dict = {
                "id": walker.id,
                "position": [location_gnss.latitude, location_gnss.longitude, location_gnss.altitude],
                "orientation": [w_transform.rotation.roll, w_transform.rotation.pitch, w_transform.rotation.yaw],
                "bounding_box": [[v.longitude, v.latitude, v.altitude] for v in _get_bounding_box(walker)]
            }
            walkers_dict[walker.id] = w_dict
        return walkers_dict

    def get_speed_limits(speed_limits):
        speed_limits_dict = dict()
        for speed_limit in speed_limits:
            sl_transform = speed_limit.get_transform()
            location_gnss = carla_map.transform_to_geolocation(sl_transform.location)
            sl_dict = {
                "id": speed_limit.id,
                "position": [location_gnss.latitude, location_gnss.longitude, location_gnss.altitude],
                "speed": int(speed_limit.type_id.split('.')[2])
            }
            speed_limits_dict[speed_limit.id] = sl_dict
        return speed_limits_dict

    def get_static_obstacles(static_obstacles):
        static_obstacles_dict = dict()
        for static_prop in static_obstacles:
            sl_transform = static_prop.get_transform()
            location_gnss = carla_map.transform_to_geolocation(sl_transform.location)
            sl_dict = {
                "id": static_prop.id,
                "position": [location_gnss.latitude, location_gnss.longitude, location_gnss.altitude]
            }
            static_obstacles_dict[static_prop.id] = sl_dict
        return static_obstacles_dict

    actors = carla_world.get_actors()
    vehicles, traffic_lights, speed_limits, walkers, stops, static_obstacles = _split_actors(actors)

    hero_vehicles = [vehicle for vehicle in vehicles if
                     'vehicle' in vehicle.type_id and vehicle.attributes['role_name'] == 'hero']
    hero = None if len(hero_vehicles) == 0 else random.choice(hero_vehicles)

    return {
        'vehicles': get_vehicles(vehicles),
        'hero_vehicle': get_hero_vehicle(hero),
        'walkers': get_walkers(walkers),
        'traffic_lights': get_traffic_lights(traffic_lights),
        'stop_signs': get_stop_signals(stops),
        'speed_limits': get_speed_limits(speed_limits),
        'static_obstacles': get_static_obstacles(static_obstacles)
    }
