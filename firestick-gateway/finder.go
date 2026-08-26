package main

import (
	"fmt"
	"strings"
)

// LeadFinder handles niche-based business exploration
type LeadFinder struct {
	Niches []string
}

func NewLeadFinder() *LeadFinder {
	return &LeadFinder{
		Niches: []string{
			"roof", "roofer", "hvac", "air conditioning",
			"heating", "cooling", "solar", "remodeler",
			"remodeling", "renovation", "detail", "detailing",
			"ceramic", "tree", "arborist",
		},
	}
}

func (lf *LeadFinder) IsTargetNiche(query string) bool {
	q := strings.ToLower(query)
	for _, niche := range lf.Niches {
		if strings.Contains(q, niche) {
			return true
		}
	}
	return false
}

func (lf *LeadFinder) Search(niche string) {
	if lf.IsTargetNiche(niche) {
		fmt.Printf("Valid target niche identified: %s\n", niche)
	} else {
		fmt.Printf("Niche %s not in scope.\n", niche)
	}
}
