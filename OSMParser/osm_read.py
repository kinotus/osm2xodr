from bz2 import BZ2File

from lxml.etree import iterparse
from osmread import Node, Relation, Way
from osmread import parse_file as _parse_pbf_file
from osmread.elements import RelationMember


def _integer_attribute(attributes, name):
    return int(attributes.get(name, 0))


def _tags(element):
    return {
        child.get("k", ""): child.get("v", "")
        for child in element
        if child.tag.rsplit("}", 1)[-1] == "tag"
    }


def _parse_xml_stream(source):
    for _, element in iterparse(source, events=("end",)):
        element_type = element.tag.rsplit("}", 1)[-1]
        if element_type == "node":
            yield Node(
                int(element.get("id")),
                _integer_attribute(element.attrib, "version"),
                _integer_attribute(element.attrib, "changeset"),
                0,
                _integer_attribute(element.attrib, "uid"),
                _tags(element),
                float(element.get("lon")),
                float(element.get("lat")),
            )
        elif element_type == "way":
            yield Way(
                int(element.get("id")),
                _integer_attribute(element.attrib, "version"),
                _integer_attribute(element.attrib, "changeset"),
                0,
                _integer_attribute(element.attrib, "uid"),
                _tags(element),
                tuple(
                    int(child.get("ref"))
                    for child in element
                    if child.tag.rsplit("}", 1)[-1] == "nd"
                ),
            )
        elif element_type == "relation":
            member_types = {"node": Node, "way": Way, "relation": Relation}
            members = tuple(
                RelationMember(
                    child.get("role", ""),
                    member_types.get(child.get("type"), Relation),
                    int(child.get("ref")),
                )
                for child in element
                if child.tag.rsplit("}", 1)[-1] == "member"
            )
            yield Relation(
                int(element.get("id")),
                _integer_attribute(element.attrib, "version"),
                _integer_attribute(element.attrib, "changeset"),
                0,
                _integer_attribute(element.attrib, "uid"),
                _tags(element),
                members,
            )

        if element_type in ("node", "way", "relation"):
            element.clear()


def _parse_xml(path):
    if str(path).endswith(".bz2"):
        with BZ2File(str(path), "rb") as source:
            yield from _parse_xml_stream(source)
    else:
        yield from _parse_xml_stream(str(path))


def parse_file(path, **kwargs):
    path_string = str(path)
    file_format = kwargs.get("format")
    if file_format == "xml" or path_string.endswith((".osm", ".xml", ".osm.bz2", ".xml.bz2")):
        yield from _parse_xml(path_string)
    else:
        yield from _parse_pbf_file(path_string, **kwargs)
