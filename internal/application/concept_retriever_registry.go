package application

import "errors"

var ErrUnknownConceptRetriever = errors.New("unknown concept retriever")

// ConceptRetrieverRegistry owns deterministic retriever selection for the
// application. Transport supplies only the requested name.
type ConceptRetrieverRegistry struct {
	defaultName string
	retrievers  map[string]ConceptRetriever
}

func NewConceptRetrieverRegistry(defaultRetriever ConceptRetriever, additional ...ConceptRetriever) *ConceptRetrieverRegistry {
	registry := &ConceptRetrieverRegistry{
		defaultName: defaultRetriever.Name(),
		retrievers:  make(map[string]ConceptRetriever, len(additional)+1),
	}
	registry.retrievers[defaultRetriever.Name()] = defaultRetriever
	for _, retriever := range additional {
		registry.retrievers[retriever.Name()] = retriever
	}
	return registry
}

func (r *ConceptRetrieverRegistry) Select(name string) (ConceptRetriever, error) {
	if name == "" {
		name = r.defaultName
	}
	retriever, ok := r.retrievers[name]
	if !ok {
		return nil, ErrUnknownConceptRetriever
	}
	return retriever, nil
}
